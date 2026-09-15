# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `93c587109e1163e9206872e91ddce5eb1c55ad0b34a9b5b43dbc4df887a3e4b4`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 21.525 physische Zeilen
- Inventareinträge: 1.685
- Definitionen (Funktionen/Klassen): 1.204
- Globale Bindungen einschließlich Imports: 283 Zuweisungen. 198 Imports
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
| P1 | 62 | 47 | 146 |
| P2 | 162 | 24 | 0 |
| P3 | 181 | 27 | 0 |
| P4 | 305 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 217 | 47 | 0 |
| P7 | 189 | 37 | 0 |
| P8 | 18 | 13 | 0 |
| P9 | 18 | 6 | 0 |
| P10 | 27 | 39 | 0 |
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
- `tests/test_audit_remediation.py:190: startup = patch.object(server, "security_configuration_error", return_value=None)`
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
- `tests/test_provider_review.py:184: patch.object(server, "security_configuration_error", return_value=None), \`
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
- `tests/test_provider_review.py:323: with patch.object(server, "DB_PATH", encrypted_path), patch.object(server, "CONFIG", configured), \`
- `tests/test_provider_review.py:324: patch.object(server, "allow_rate", return_value=(True, 0)):`
- `tests/test_provider_review.py:32: patch.object(server.observability, "configure_logging"),`
- `tests/test_provider_review.py:81: with patch.object(server.IntervalsClient, "fetch_performance_snapshot", side_effect=fetch):`
- `tests/test_server.py:1166: with patch.object(server, "_fetch_weather_forecast", side_effect=[old, new]) as fetch:`
- `tests/test_server.py:1192: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1220: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1234: with patch.object(server, "_fetch_weather_forecast", return_value=forecast) as fetch:`
- `tests/test_server.py:1253: with patch.object(server, "_fetch_weather_forecast", side_effect=[server.AppError(503, "upstream"), forecast]) as fetch:`
- `tests/test_server.py:1269: with patch.object(server, "CONFIG", replace(server.CONFIG, secure_cookies=True)):`
- `tests/test_server.py:1487: with patch.object(server, "delete_remote_conversation", side_effect=server.AppError(503, "upstream")):`
- `tests/test_server.py:1503: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:1520: with patch.object(server, "_fetch_weather_forecast", return_value=forecast), patch.object(`
- `tests/test_server.py:1536: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("coach context must not refresh weather")):`
- `tests/test_server.py:1546: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1563: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1573: with patch.object(server, "latest_replan_preview", return_value={"status": "preview", "changes": [{"date": "2026-09-01"}]}):`
- `tests/test_server.py:1597: self.assertEqual(getattr(server.local_now().tzinfo, "key", None), "UTC")`
- `tests/test_server.py:1616: with patch.object(server, "local_now", return_value=fixed_now):`
- `tests/test_server.py:1737: with patch.object(server, "http_json", side_effect=AssertionError("network")), patch.object(server, "external_call", side_effect=AssertionError("network")):`
- `tests/test_server.py:174: with patch.object(server, "CONFIG", config), patch.object(server, "DATA_DIR", Path(temporary)), patch.object(`
- `tests/test_server.py:1780: with patch.object(server.sqlite3, "connect", wraps=sqlite3.connect) as connect:`
- `tests/test_server.py:1858: with patch.object(server, "state_versions", return_value={"activities": "v1"}):`
- `tests/test_server.py:212: with patch.object(server, "_execute_sync_job", return_value={"status": "ok"}):`
- `tests/test_server.py:223: with patch.object(server, "_execute_sync_job", side_effect=server.AppError(503, provider_detail, reason="network_error")):`
- `tests/test_server.py:234: with patch.object(server, "sync_garmin") as sync:`
- `tests/test_server.py:2534: with patch.object(server, "CONFIG", replace(server.CONFIG, calendar_ical_url="https://calendar.example/feed.ics")), patch.object(`
- `tests/test_server.py:2536: ), patch.object(server, "fetch_calendar_feed", return_value=b"not an ical feed"):`
- `tests/test_server.py:2542: with patch.object(server.socket, "getaddrinfo", return_value=[(None, None, None, None, ("100.64.0.1", 443))]):`
- `tests/test_server.py:2566: with patch.object(server, "_resolve_calendar_addresses", return_value=addresses) as resolve, patch.object(`
- `tests/test_server.py:2568: ), patch.object(server.socket, "create_connection", side_effect=[OSError("first address unavailable"), raw_socket]) as connect, patch.object(`
- `tests/test_server.py:256: with patch.object(server, "_execute_sync_job", return_value=result):`
- `tests/test_server.py:2582: ), patch.object(server.socket, "create_connection", side_effect=TimeoutError("calendar timeout")):`
- `tests/test_server.py:2621: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload), patch.object(`
- `tests/test_server.py:2650: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload):`
- `tests/test_server.py:2665: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", side_effect=server.AppError(502, "upstream unavailable")):`
- `tests/test_server.py:266: with patch.object(server, "_repair_local_planned_unit_calendar_entry", return_value=None) as repair:`
- `tests/test_server.py:2732: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:2827: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=-1)):`
- `tests/test_server.py:2836: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=30)):`
- `tests/test_server.py:2846: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:2893: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)):`
- `tests/test_server.py:2953: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 20, 0)):`
- `tests/test_server.py:2980: patch.object(server, "latest_snapshot", return_value=snapshot),`
- `tests/test_server.py:2981: patch.object(server, "list_dated_local_planned_workouts", return_value=planned),`
- `tests/test_server.py:2982: patch.object(server, "weather_state", return_value={"days": []}),`
- `tests/test_server.py:2983: patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)),`
- `tests/test_server.py:3387: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:344: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-plan-push"}) as enqueue:`
- `tests/test_server.py:375: with patch.object(server, "_mark_local_planning_authoritative"), patch.object(`
- `tests/test_server.py:3882: with patch.object(server.IntervalsClient, "get_workout_library", return_value=[]), \`
- `tests/test_server.py:3883: patch.object(server.IntervalsClient, "create_library_workouts", return_value=[{"id": "synthetic-remote", "type": "Ride"}]) as create, \`
- `tests/test_server.py:3884: patch.object(server.IntervalsClient, "update_library_workout", return_value={"id": "synthetic-remote", **parsed_workout_fixture()}) as update:`
- `tests/test_server.py:3902: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=[`
- `tests/test_server.py:3927: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:3945: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:3947: ), patch.object(server.IntervalsClient, "create_library_workouts") as create:`
- `tests/test_server.py:399: with patch.object(server, "_enqueue_coach_plan_push") as enqueue, self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:4154: with patch.object(server, "garmin_fixture_path", return_value="fixture.json"), \`
- `tests/test_server.py:4155: patch.object(server, "sync_garmin") as sync_garmin, \`
- `tests/test_server.py:4156: patch.object(server, "garmin_sleep_ready_for_checkin", return_value=False), \`
- `tests/test_server.py:4201: with patch.object(server, "CONFIG", config), patch.object(server, "Garmin", FakeGarmin):`
- `tests/test_server.py:431: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-competition"}) as enqueue:`
- `tests/test_server.py:4370: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4414: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=fake_urlopen):`
- `tests/test_server.py:4439: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4563: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value=response):`
- `tests/test_server.py:4578: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4589: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4603: with patch.object(server, "CONFIG", replace(server.CONFIG, gemini_api_key=key)):`
- `tests/test_server.py:4609: with patch.object(server, "CONFIG", config), patch.object(server, "gemini_responses_request", return_value={"output_text": "ok"}) as gemini, patch.object(server, "openai_request") as openai:`
- `tests/test_server.py:4622: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4642: with patch.object(server, "CONFIG", config), patch.object(server, "delete_remote_conversation", return_value=True) as delete:`
- `tests/test_server.py:4666: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:4713: with patch.object(server, "urlopen", side_effect=blocked_urlopen):`
- `tests/test_server.py:4744: with patch.object(server, "urlopen", return_value=response):`
- `tests/test_server.py:4777: with patch.object(server, "urlopen", side_effect=return_cancelled_response):`
- `tests/test_server.py:4796: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")), patch.object(`
- `tests/test_server.py:4815: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4818: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url="")):`
- `tests/test_server.py:4826: with self.subTest(invalid=invalid), patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url=invalid)):`
- `tests/test_server.py:4839: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4863: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:4870: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:5042: with patch.object(server, "calendar_conflicts", return_value=[{"name": "Occupied"}]) as conflicts:`
- `tests/test_server.py:527: with patch.object(server, "enqueue_sync_job", side_effect=[{"id": "job-performance"}, {"id": "job-competition"}]) as enqueue:`
- `tests/test_server.py:5356: with patch.object(server, "structured_athlete_context", return_value={"source_policy": {"untrusted": "x" * 200_000}}):`
- `tests/test_server.py:5463: with patch.object(server, "openai_request", side_effect=fake_openai):`
- `tests/test_server.py:5469: with patch.object(server, "http_json", return_value=response), patch.object(`
- `tests/test_server.py:5485: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:550: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:5599: with patch.object(server, "CHANGE_HISTORY_MAX_ROWS", 3), self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:563: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:5736: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 2):`
- `tests/test_server.py:574: with patch.object(server, "sync_intervals", return_value={"status": "ok"}) as sync, patch.object(`
- `tests/test_server.py:5750: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 1):`
- `tests/test_server.py:5836: with patch.object(server, "save_workout_library_entries", side_effect=RuntimeError("creation failed")):`
- `tests/test_server.py:5838: server._apply_training_patch(arguments, {`
- `tests/test_server.py:5855: with patch.object(server, "responses_request", side_effect=create), patch.object(`
- `tests/test_server.py:5860: ) as retrieve, patch.object(server, "OPENAI_BACKGROUND_POLL_SECONDS", 0), patch.object(server, "record_openai_usage"):`
- `tests/test_server.py:586: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:5908: with patch.object(server, "chat_with_coach", side_effect=lambda *args, **kwargs: seen.update(kwargs) or {}):`
- `tests/test_server.py:5932: with patch.object(server, "chat_with_coach", side_effect=complete_chat):`
- `tests/test_server.py:5961: with patch.object(server, "responses_stream_request", side_effect=streamed_response) as streamed, patch.object(`
- `tests/test_server.py:5986: ), patch.object(server, "_restore_coach_session_csrf_hash", return_value="csrf-background-requeue"):`
- `tests/test_server.py:6027: with patch.object(server, "chat_with_coach", side_effect=capture_phase), patch.object(`
- `tests/test_server.py:605: with patch.object(server, "CONFIG", config), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:6063: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6065: ) as fetch_snapshot, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:6076: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6092: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6094: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6105: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6107: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6123: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6136: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:614: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6164: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6166: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=remote) as get_library:`
- `tests/test_server.py:616: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:618: ) as enqueue, patch.object(server, "_wait_for_performance_refresh") as wait:`
- `tests/test_server.py:6204: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6206: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6226: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6230: ) as import_units, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6248: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6250: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[{`
- `tests/test_server.py:6267: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6271: ) as library_sync, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:627: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6286: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:629: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:6340: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6349: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6368: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6377: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6386: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6394: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6411: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6455: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6469: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_server.py:6487: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6532: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6534: ), patch.object(server, "_sync_selected_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6557: with patch.object(server, "IntervalsClient", FailingIntervalsClient), patch.object(`
- `tests/test_server.py:6567: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6580: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", db_path), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6625: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:6646: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6655: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir), patch.dict(`
- `tests/test_server.py:6675: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir):`
- `tests/test_server.py:6822: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6854: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6892: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6924: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6940: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6979: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7012: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7039: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7322: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:7323: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:7452: with patch.object(server, "http_json", side_effect=[`
- `tests/test_server.py:7535: with patch.object(server.LOGGER, "info") as logger:`
- `tests/test_server.py:7712: with patch.object(server.IntervalsClient, "delete_activity", return_value=None) as delete:`
- `tests/test_server.py:7762: with patch.object(server, "get_kv", side_effect=get_kv_after_read):`
- `tests/test_server.py:7794: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7816: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7822: with patch.object(server, "external_calendar_url", return_value=calendar_url), patch.object(`
- `tests/test_server.py:7844: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7863: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7880: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7914: with patch.object(server, "urlopen", side_effect=server.URLError("offline")):`
- `tests/test_server.py:7931: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7945: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7955: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7971: with patch.object(server, "database", side_effect=OSError("database unavailable")):`
- `tests/test_server.py:7979: with patch.object(server.tempfile, "NamedTemporaryFile", side_effect=OSError("read-only")):`
- `tests/test_server.py:7998: with patch.object(server.time, "monotonic", return_value=20 * 60):`
- `tests/test_server.py:8027: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:8029: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[]):`
- `tests/test_server.py:8056: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8092: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8119: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8160: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8195: with patch.object(server, "openai_request", side_effect=fake_request), patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8266: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8308: with patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:8321: with patch.object(server, "urlopen") as urlopen:`
- `tests/test_server.py:8345: with patch.object(server, "urlopen", return_value=TimeoutResponse()):`
- `tests/test_server.py:8370: with patch.object(server, "urlopen", return_value=DisconnectResponse()):`
- `tests/test_server.py:8378: with patch.object(server, "openai_stream_request", side_effect=responses) as request, patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8425: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), \`
- `tests/test_server.py:8426: patch.object(server, "unregister_chat_stream") as unregister, \`
- `tests/test_server.py:8427: patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8452: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), patch.object(`
- `tests/test_server.py:8454: ) as unregister, patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8506: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value={"status": "completed"}) as request:`
- `tests/test_server.py:8559: with patch.object(server, "DB_LOCK", database_lock), patch.object(`
- `tests/test_server.py:8576: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8663: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:8677: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:867: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-changed"}) as enqueue:`
- `tests/test_server.py:8688: with patch.object(server, "CONFIG", replace(config, intervals_api_key="")):`
- `tests/test_server.py:8745: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:893: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-large-changed"}) as enqueue:`
- `tests/test_server.py:938: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-all"}) as enqueue:`
- `tests/test_server.py:975: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=True) as active, patch.object(`
- `tests/test_server.py:984: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=False), patch.object(`
- `tests/test_server.py:986: ), patch.object(server, "enqueue_sync_job") as enqueue:`
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
| `ProviderResyncGate` | 314 | – | `AppError`, `contextmanager`, `threading` | – | – |
| `provider_operation` | 365 | – | `GARMIN_RESYNC_GATE`, `INTERVALS_RESYNC_GATE` | – | – |
| `intervals_operation` | 370 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `garmin_operation` | 378 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `load_local_env` | 386 | – | `DATA_DIR`, `ROOT`, `load_config_env` | – | – |
| `IntervalsClient` | 394 | `_raise_chat_cancelled`, `compact_snapshot`, `deduplicate_api_records`, `intervals_workout_sport`, `latest_snapshot`, `local_now`, `selected`, `sync_date_windows`, `validate_intervals_workout_result`, `validate_workout_description`, `workout_event_payload` | `ALL_SYNC_DAYS`, `APP_NAME`, `Any`, `AppError`, `CONFIG`, `Callable`, `Config`, `IntervalsReadTransport`, `IntervalsWriteTransport`, `PLANNED_CALENDAR_FUTURE_DAYS`, `PLANNED_CALENDAR_HISTORY_DAYS`, `_raise_chat_cancelled`, … (+18) | – | – |
| `external_call` | 701 | `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `operation_error_code` | `Any`, `AppError`, `DATA_DIR`, `LOGGER`, `LOG_PATH`, `OPERATION_CONTEXT`, `REDACTOR`, `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `observability`, … (+3) | – | – |
| `serialise_conversation` | 893 | – | `AppError`, `CHAT_LOCK_TIMEOUT_SECONDS`, `CHAT_QUEUE`, `OPENAI_CONVERSATION_LOCK`, `wraps` | – | – |
| `utc_now` | 910 | – | `datetime`, `timezone` | – | – |
| `security_configuration_error` | 925 | – | `CONFIG`, `SQLCIPHER_AVAILABLE` | – | – |
| `operation_trigger` | 1016 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 1022 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 1031 | – | `Any` | – | – |
| `log_operation_event` | 1041 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1068 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1089 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count`, `runtime_maintenance`, `wraps` | – | – |
| `database_manager` | 1132 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE` | – |
| `database` | 1159 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1165 | `database`, `get_kv`, `resume_interrupted_sync_jobs`, `set_kv`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `PROVIDER_RESYNC_KEYS`, `database`, `database_schema_is_current`, `database_table_names`, `datetime`, `get_kv`, `initialize_schema`, `json`, … (+5) | – | – |
| `_provider_refresh_cleanup` | 1207 | – | `Any`, `PROVIDER_REFRESH_MAX_ROWS`, `PROVIDER_REFRESH_RETENTION_DAYS`, `cleanup_refresh_history`, `datetime`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1212 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `runtime_events`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1224 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `runtime_events`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1258 | – | – | – | – |
| `_sync_job_error_class` | 1273 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1287 | – | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1296 | – | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1310 | `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1323 | `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1333 | `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1342 | – | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1352 | – | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1359 | `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1384 | `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1393 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1399 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1404 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1427 | – | `AppError` | – | – |
| `_pending_performance_job_id` | 1435 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1444 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1462 | `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1489 | – | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1498 | – | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1505 | – | `Any` | – | – |
| `_insert_sync_job` | 1515 | – | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 1540 | – | `Any`, `runtime_events` | – | – |
| `enqueue_sync_job` | 1554 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `runtime_maintenance`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 1581 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 1601 | `database`, `utc_now` | `Any`, `DB_LOCK`, `database`, `runtime_maintenance`, `utc_now` | – | – |
| `_sync_job_update` | 1622 | `database`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `runtime_events`, `utc_now` | – | – |
| `_sync_job_item_results` | 1660 | – | `Any` | – | – |
| `_sync_job_result_target` | 1666 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 1677 | `_sync_job_result_target` | `Any`, `REDACTOR`, `_sync_job_result_target` | – | – |
| `_sync_job_completion_snapshot` | 1697 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 1712 | – | `runtime_events` | – | – |
| `_sync_job_update_from_result` | 1729 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 1742 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 1751 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 1758 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 1775 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 1787 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 1799 | `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 1822 | – | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 1831 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 1851 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 1871 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | `Any`, `LOGGER`, `REDACTOR`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | – | – |
| `_run_claimed_sync_job` | 1889 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `runtime_maintenance` | – | – |
| `_sync_job_worker_loop` | 1899 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job`, `runtime_maintenance` | – | – |
| `start_sync_job_worker` | 1914 | `resume_interrupted_sync_jobs` | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `resume_interrupted_sync_jobs`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 1926 | `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_scheduled_provider_retry_at` | 1949 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_freshness_inputs` | 1968 | `_garmin_core_error_entries`, `get_kv`, `get_profile` | `Any`, `CONFIG`, `Path`, `WEATHER_CACHE_KEY`, `WEATHER_FAILURE_KEY`, `_garmin_core_error_entries`, `get_kv`, `get_profile`, `json` | – | – |
| `_provider_freshness_last_good_state` | 2002 | – | `Any`, `PROVIDER_REFRESH_STALE_SECONDS`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_fallback_error_code` | 2012 | – | – | – | – |
| `_provider_freshness_error_code` | 2016 | `_provider_fallback_error_code` | `Any`, `_provider_fallback_error_code` | – | – |
| `_provider_freshness_status` | 2024 | `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | `Any`, `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | – | – |
| `provider_freshness_state` | 2045 | `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | `Any`, `DB_LOCK`, `PROVIDER_REFRESH_LABELS`, `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | – | – |
| `_audit_projection_fields` | 2086 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 2100 | – | `Any`, `json` | – | – |
| `_audit_projection` | 2111 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 2135 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 2140 | – | `Any` | – | – |
| `_cleanup_change_history` | 2152 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 2162 | – | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 2179 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2218 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2250 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2261 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2273 | – | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2287 | – | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2303 | `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2341 | `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2361 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2371 | `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2396 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2417 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2427 | `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2436 | `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2462 | `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2478 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2507 | `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2522 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |
| `sync_period` | 2563 | `get_kv` | `ALL_SYNC_DAYS`, `SYNC_PERIOD_DEFAULTS`, `get_kv` | – | – |
| `set_sync_period` | 2574 | `set_kv` | `ALL_SYNC_DAYS`, `Any`, `AppError`, `set_kv` | – | – |
| `sync_date_windows` | 2586 | `local_now` | `ALL_SYNC_DAYS`, `SYNC_CHUNK_DAYS`, `SYNC_EARLIEST_DATE`, `date`, `local_now`, `split_date_windows` | – | – |
| `provider_sync_cursor` | 2597 | `database` | `Any`, `DB_LOCK`, `database`, `read_cursor` | – | – |
| `update_provider_sync_cursor` | 2602 | `database`, `utc_now` | `DB_LOCK`, `database`, `utc_now`, `write_cursor` | – | – |
| `set_kv` | 2608 | `database`, `set_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `set_kv`, `sqlite3` | – | – |
| `_safe_diagnostic_context` | 2619 | – | `Any` | – | – |
| `diagnostic_mapping_shape` | 2631 | `diagnostic_response_shape` | `Any`, `diagnostic_response_shape`, `re` | – | – |
| `diagnostic_sequence_shape` | 2643 | `diagnostic_response_shape` | `Any`, `diagnostic_response_shape` | – | – |
| `diagnostic_response_shape` | 2650 | `diagnostic_mapping_shape`, `diagnostic_sequence_shape` | `Any`, `diagnostic_mapping_shape`, `diagnostic_sequence_shape` | – | – |
| `diagnostic_capture_response` | 2667 | `diagnostic_response_shape` | `Any`, `diagnostic_response_shape` | – | – |
| `_safe_diagnostic_error` | 2672 | – | `Any`, `OPENAI_RESPONSE_ERROR_CODES`, `re` | – | – |
| `_coach_error_metadata` | 2690 | `_safe_diagnostic_error` | `Any`, `Path`, `ROOT`, `_safe_diagnostic_error` | – | – |
| `_safe_response_headers` | 2705 | – | `Any`, `REDACTOR` | – | – |
| `_diagnostic_capture_state` | 2722 | `get_kv` | `Any`, `DIAGNOSTIC_CAPTURE_STATE_KEY`, `get_kv`, `json` | – | – |
| `diagnostic_capture_status` | 2730 | `_diagnostic_capture_state`, `get_kv`, `set_kv` | `Any`, `DIAGNOSTIC_CAPTURE_ENTRIES_KEY`, `DIAGNOSTIC_CAPTURE_MAX_ENTRIES`, `DIAGNOSTIC_CAPTURE_STATE_KEY`, `UTC_OFFSET_SUFFIX`, `_diagnostic_capture_state`, `datetime`, `get_kv`, `json`, `set_kv`, `timezone` | – | – |
| `diagnostic_capture_entries` | 2752 | `get_kv` | `Any`, `DIAGNOSTIC_CAPTURE_ENTRIES_KEY`, `DIAGNOSTIC_CAPTURE_MAX_ENTRIES`, `REDACTOR`, `get_kv`, `json` | – | – |
| `set_diagnostic_capture` | 2762 | `diagnostic_capture_status`, `set_kv` | `Any`, `AppError`, `DIAGNOSTIC_CAPTURE_DURATION_SECONDS`, `DIAGNOSTIC_CAPTURE_ENTRIES_KEY`, `DIAGNOSTIC_CAPTURE_LOCK`, `DIAGNOSTIC_CAPTURE_STATE_KEY`, `datetime`, `diagnostic_capture_status`, `json`, `set_kv`, `timedelta`, `timezone` | – | – |
| `capture_diagnostic_event` | 2777 | `diagnostic_capture_entries`, `diagnostic_capture_status`, `set_kv`, `utc_now` | `Any`, `DIAGNOSTIC_CAPTURE_ENTRIES_KEY`, `DIAGNOSTIC_CAPTURE_LOCK`, `DIAGNOSTIC_CAPTURE_MAX_ENTRIES`, `REDACTOR`, `diagnostic_capture_entries`, `diagnostic_capture_status`, `json`, `set_kv`, `utc_now` | – | – |
| `garmin_snapshot` | 2791 | `get_kv` | `Any`, `get_kv`, `json` | – | – |
| `garmin_configured` | 2799 | – | `CONFIG`, `Garmin` | – | – |
| `garmin_fixture_path` | 2803 | – | `CONFIG`, `Path`, `ROOT` | – | – |
| `activity_datetime` | 2811 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `activity_kind` | 2823 | – | `Any` | – | – |
| `_cycling_event_candidates` | 2838 | `activity_kind` | `Any`, `activity_kind` | – | – |
| `_cycling_event_interval` | 2848 | `activity_datetime`, `as_number` | `Any`, `activity_datetime`, `as_number`, `datetime`, `timedelta` | – | – |
| `_cycling_intervals_share_group` | 2859 | – | `datetime` | – | – |
| `_cycling_event_edges` | 2868 | `_cycling_intervals_share_group` | `_cycling_intervals_share_group`, `datetime` | – | – |
| `_cycling_event_group` | 2883 | – | `Any` | – | – |
| `parallel_cycling_event_groups` | 2897 | `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | `Any`, `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | – | – |
| `_garmin_duplicate_measurements` | 2909 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_activity_matches` | 2925 | `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | `Any`, `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | – | – |
| `garmin_activity_duplicates_intervals` | 2940 | `_garmin_activity_matches` | `Any`, `_garmin_activity_matches` | – | – |
| `filter_garmin_activities` | 2947 | `garmin_activity_duplicates_intervals` | `Any`, `garmin_activity_duplicates_intervals` | – | – |
| `intervals_activity_device_source` | 2954 | – | `Any` | – | – |
| `intervals_cycling_activities_match` | 2969 | `activity_datetime`, `activity_kind`, `as_number`, `first_present` | `Any`, `activity_datetime`, `activity_kind`, `as_number`, `first_present` | – | – |
| `_latest_activity_id` | 2992 | `activity_datetime`, `first_present` | `Any`, `activity_datetime`, `first_present` | – | – |

### Zyklische Gruppen

Statisch erkannte SCCs im direkten lokalen Aufrufgraphen: 13. Jede Gruppe ist als gemeinsame Umzugseinheit zu prüfen.

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
| Importbindung | `ipaddress` | 12 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2564 (direkt/dynamisch unklar); tests/test_server.py:2581 (direkt/dynamisch unklar) |
| Importbindung | `json` | 13 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_workout_repair.py:572 (direkt/dynamisch unklar) |
| Importbindung | `logging` | 14 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `math` | 15 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `mimetypes` | 16 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `os` | 17 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `platform` | 18 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `queue` | 19 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:8421 (direkt/dynamisch unklar); tests/test_server.py:8447 (direkt/dynamisch unklar) |
| Importbindung | `re` | 20 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `secrets` | 21 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_coach_language_recovery.py:42 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:69 (direkt/dynamisch unklar) |
| Importbindung | `shutil` | 22 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `socket` | 23 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2542 (direkt/dynamisch unklar); tests/test_server.py:2549 (direkt/dynamisch unklar); tests/test_server.py:2568 (direkt/dynamisch unklar); tests/test_server.py:2582 (direkt/dynamisch unklar) |
| Importbindung | `ssl` | 24 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2567 (direkt/dynamisch unklar) |
| Importbindung | `sqlite3` | 25 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1023 (direkt/dynamisch unklar); tests/test_server.py:1198 (direkt/dynamisch unklar); tests/test_server.py:1780 (direkt/dynamisch unklar) |
| Importbindung | `threading` | 26 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_diagnostic_followups.py:170 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:37 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:56 (direkt/dynamisch unklar) |
| Importbindung | `tempfile` | 27 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7979 (direkt/dynamisch unklar) |
| Importbindung | `time` | 28 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/support.py:130 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:108 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:41 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:95 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:38 (direkt/dynamisch unklar); tests/test_coach_review.py:257 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:257 (direkt/dynamisch unklar); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:1325 (direkt/dynamisch unklar); tests/test_server.py:4236 (direkt/dynamisch unklar); tests/test_server.py:7998 (direkt/dynamisch unklar); tests/test_server.py:8195 (direkt/dynamisch unklar); tests/test_server.py:8378 (direkt/dynamisch unklar) |
| Importbindung | `uuid` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `zipfile` | 30 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ContextVar` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `nullcontext` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `contextmanager` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `dataclass` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `date` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1573 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `datetime` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `timedelta` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:496 (direkt/dynamisch unklar) |
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
| Importbindung | `HTTPError` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4659 (direkt/dynamisch unklar); tests/test_server.py:7842 (direkt/dynamisch unklar); tests/test_server.py:7873 (direkt/dynamisch unklar); tests/test_server.py:7924 (direkt/dynamisch unklar); tests/test_server.py:8109 (direkt/dynamisch unklar); tests/test_server.py:8153 (direkt/dynamisch unklar); tests/test_server.py:8168 (direkt/dynamisch unklar); tests/test_server.py:8261 (direkt/dynamisch unklar) |
| Importbindung | `URLError` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7914 (direkt/dynamisch unklar) |
| Importbindung | `parse_qs` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `quote` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlencode` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlparse` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlunparse` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Request` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlopen` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4414 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4666 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4713 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4744 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4777 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4863 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7844 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7863 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7880 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7914 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7931 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8056 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8092 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8119 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8160 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8308 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8321 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8345 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8370 (Monkeypatch/getattr/sys.modules) |
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
| Importbindung | `AppError` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:161 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1363 (direkt/dynamisch unklar); tests/test_server.py:1370 (direkt/dynamisch unklar); tests/test_server.py:1487 (direkt/dynamisch unklar); tests/test_server.py:1588 (direkt/dynamisch unklar); tests/test_server.py:1592 (direkt/dynamisch unklar); tests/test_server.py:1618 (direkt/dynamisch unklar); tests/test_server.py:1755 (direkt/dynamisch unklar); tests/test_server.py:2006 (direkt/dynamisch unklar); tests/test_server.py:2012 (direkt/dynamisch unklar); tests/test_server.py:2023 (direkt/dynamisch unklar); tests/test_server.py:2027 (direkt/dynamisch unklar); tests/test_server.py:2028 (direkt/dynamisch unklar); tests/test_server.py:2030 (direkt/dynamisch unklar); tests/test_server.py:2035 (direkt/dynamisch unklar); tests/test_server.py:2038 (direkt/dynamisch unklar); tests/test_server.py:2043 (direkt/dynamisch unklar); tests/test_server.py:2046 (direkt/dynamisch unklar); tests/test_server.py:2051 (direkt/dynamisch unklar); tests/test_server.py:2054 (direkt/dynamisch unklar); tests/test_server.py:2061 (direkt/dynamisch unklar); tests/test_server.py:2086 (direkt/dynamisch unklar); tests/test_server.py:223 (direkt/dynamisch unklar); tests/test_server.py:2342 (direkt/dynamisch unklar); tests/test_server.py:235 (direkt/dynamisch unklar); tests/test_server.py:2452 (direkt/dynamisch unklar); tests/test_server.py:2477 (direkt/dynamisch unklar); tests/test_server.py:2481 (direkt/dynamisch unklar); tests/test_server.py:2524 (direkt/dynamisch unklar); tests/test_server.py:2537 (direkt/dynamisch unklar); tests/test_server.py:2543 (direkt/dynamisch unklar); tests/test_server.py:2583 (direkt/dynamisch unklar); tests/test_server.py:2665 (direkt/dynamisch unklar); tests/test_server.py:2666 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2673 (direkt/dynamisch unklar); tests/test_server.py:288 (direkt/dynamisch unklar); tests/test_server.py:320 (direkt/dynamisch unklar); tests/test_server.py:3213 (direkt/dynamisch unklar); tests/test_server.py:3250 (direkt/dynamisch unklar); tests/test_server.py:3684 (direkt/dynamisch unklar); tests/test_server.py:3784 (direkt/dynamisch unklar); tests/test_server.py:3800 (direkt/dynamisch unklar); tests/test_server.py:3839 (direkt/dynamisch unklar); tests/test_server.py:3866 (direkt/dynamisch unklar); tests/test_server.py:3874 (direkt/dynamisch unklar); tests/test_server.py:3885 (direkt/dynamisch unklar); tests/test_server.py:3906 (direkt/dynamisch unklar); tests/test_server.py:3918 (direkt/dynamisch unklar); tests/test_server.py:3922 (direkt/dynamisch unklar); tests/test_server.py:399 (direkt/dynamisch unklar); tests/test_server.py:4110 (direkt/dynamisch unklar); tests/test_server.py:4271 (direkt/dynamisch unklar); tests/test_server.py:4332 (direkt/dynamisch unklar); tests/test_server.py:4429 (direkt/dynamisch unklar); tests/test_server.py:4442 (direkt/dynamisch unklar); tests/test_server.py:4452 (direkt/dynamisch unklar); tests/test_server.py:4467 (direkt/dynamisch unklar); tests/test_server.py:4481 (direkt/dynamisch unklar); tests/test_server.py:4564 (direkt/dynamisch unklar); tests/test_server.py:4654 (direkt/dynamisch unklar); tests/test_server.py:4656 (direkt/dynamisch unklar); tests/test_server.py:4667 (direkt/dynamisch unklar); tests/test_server.py:4710 (direkt/dynamisch unklar); tests/test_server.py:4778 (direkt/dynamisch unklar); tests/test_server.py:4827 (direkt/dynamisch unklar); tests/test_server.py:4871 (direkt/dynamisch unklar); tests/test_server.py:4873 (direkt/dynamisch unklar); tests/test_server.py:488 (direkt/dynamisch unklar); tests/test_server.py:4897 (direkt/dynamisch unklar); tests/test_server.py:4972 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5208 (direkt/dynamisch unklar); tests/test_server.py:5225 (direkt/dynamisch unklar); tests/test_server.py:5431 (direkt/dynamisch unklar); tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:5448 (direkt/dynamisch unklar); tests/test_server.py:5450 (direkt/dynamisch unklar); tests/test_server.py:5599 (direkt/dynamisch unklar); tests/test_server.py:5712 (direkt/dynamisch unklar); tests/test_server.py:5764 (direkt/dynamisch unklar); tests/test_server.py:5777 (direkt/dynamisch unklar); tests/test_server.py:5985 (direkt/dynamisch unklar); tests/test_server.py:6091 (direkt/dynamisch unklar); tests/test_server.py:6095 (direkt/dynamisch unklar); tests/test_server.py:6104 (direkt/dynamisch unklar); tests/test_server.py:6108 (direkt/dynamisch unklar); tests/test_server.py:6126 (direkt/dynamisch unklar); tests/test_server.py:6137 (direkt/dynamisch unklar); tests/test_server.py:6604 (direkt/dynamisch unklar); tests/test_server.py:6617 (direkt/dynamisch unklar); tests/test_server.py:6629 (direkt/dynamisch unklar); tests/test_server.py:739 (direkt/dynamisch unklar); tests/test_server.py:7552 (direkt/dynamisch unklar); tests/test_server.py:7559 (direkt/dynamisch unklar); tests/test_server.py:758 (direkt/dynamisch unklar); tests/test_server.py:7817 (direkt/dynamisch unklar); tests/test_server.py:7825 (direkt/dynamisch unklar); tests/test_server.py:7845 (direkt/dynamisch unklar); tests/test_server.py:7881 (direkt/dynamisch unklar); tests/test_server.py:7915 (direkt/dynamisch unklar); tests/test_server.py:7932 (direkt/dynamisch unklar); tests/test_server.py:8120 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8175 (direkt/dynamisch unklar); tests/test_server.py:8186 (direkt/dynamisch unklar); tests/test_server.py:8267 (direkt/dynamisch unklar); tests/test_server.py:8322 (direkt/dynamisch unklar); tests/test_server.py:8346 (direkt/dynamisch unklar); tests/test_server.py:8376 (direkt/dynamisch unklar); tests/test_server.py:8389 (direkt/dynamisch unklar); tests/test_server.py:8392 (direkt/dynamisch unklar); tests/test_server.py:8484 (direkt/dynamisch unklar); tests/test_server.py:8493 (direkt/dynamisch unklar); tests/test_server.py:8496 (direkt/dynamisch unklar); tests/test_server.py:8499 (direkt/dynamisch unklar); tests/test_server.py:8577 (direkt/dynamisch unklar); tests/test_server.py:8626 (direkt/dynamisch unklar); tests/test_server.py:8647 (direkt/dynamisch unklar); tests/test_server.py:8747 (direkt/dynamisch unklar); tests/test_server.py:963 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Importbindung | `ClientDisconnected` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8371 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8420 (direkt/dynamisch unklar) |
| Importbindung | `provider_error` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `public_app_error_status` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4655 (direkt/dynamisch unklar); tests/test_server.py:4656 (direkt/dynamisch unklar) |
| Importbindung | `observability` | 68 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_provider_review.py:32 (direkt/dynamisch unklar); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7843 (direkt/dynamisch unklar); tests/test_server.py:7913 (direkt/dynamisch unklar); tests/test_server.py:8026 (direkt/dynamisch unklar); tests/test_server.py:8055 (direkt/dynamisch unklar); tests/test_server.py:8329 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar) |
| Importbindung | `runtime_events` | 69 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `runtime_maintenance` | 70 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `SettingsService` | 71 | `backend/settings` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ActivityFeedbackRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1114 (direkt/dynamisch unklar) |
| Importbindung | `ChatRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1040 (direkt/dynamisch unklar) |
| Importbindung | `CheckinRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1048 (direkt/dynamisch unklar) |
| Importbindung | `CompetitionRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1080 (direkt/dynamisch unklar) |
| Importbindung | `KeyValueRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1031 (direkt/dynamisch unklar); tests/test_server.py:1065 (direkt/dynamisch unklar) |
| Importbindung | `PlanAdjustmentRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1104 (direkt/dynamisch unklar) |
| Importbindung | `ProfileRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1065 (direkt/dynamisch unklar) |
| Importbindung | `SnapshotRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1127 (direkt/dynamisch unklar) |
| Importbindung | `TrainingPlanRepository` | 72 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1089 (direkt/dynamisch unklar) |
| Importbindung | `DatabaseManager` | 73 | `backend/db/manager` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CURRENT_DATABASE_INDEXES` | 74 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:160 (direkt/dynamisch unklar) |
| Importbindung | `CURRENT_DATABASE_SCHEMA` | 74 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1495 (direkt/dynamisch unklar); tests/test_server.py:159 (direkt/dynamisch unklar) |
| Importbindung | `configure_cipher` | 74 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `database_index_names` | 74 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:160 (direkt/dynamisch unklar) |
| Importbindung | `database_schema_is_current` | 74 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:158 (direkt/dynamisch unklar) |
| Importbindung | `database_table_names` | 74 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:159 (direkt/dynamisch unklar) |
| Importbindung | `initialize_schema` | 74 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `Config` | 83 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `DEFAULT_OPENAI_BASE_URL` | 83 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4819 (direkt/dynamisch unklar) |
| Importbindung | `load_config` | 83 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `load_config_env` | 83 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsReadTransport` | 84 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsWriteTransport` | 84 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `fetch_paged_collection` | 84 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_function_tools` | 85 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_response_text` | 85 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_failure_reason` | 86 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_text` | 86 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_error_detail` | 87 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_bounded_response` | 87 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `WorkoutTextError` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `canonical_workout_zones` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `structured_duration` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `verify_workout_readback` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GarminCollectionOptions` | 89 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `collect_garmin_data` | 89 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:241 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `ical_duration` | 90 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_date` | 90 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_value` | 90 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `unfold_ical` | 90 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `split_date_windows` | 91 | `backend/sync/windows` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_cursor` | 92 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `write_cursor` | 92 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_sync_operation_state` | 93 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `project_sync_status` | 93 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `daily_sync_is_due` | 94 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_daily_sync_value` | 94 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `cleanup_refresh_history` | 95 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `create_refresh_record` | 95 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `finish_refresh_record` | 95 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `latest_snapshot_in_transaction` | 96 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `save_snapshot_in_transaction` | 96 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ReconcileDependencies` | 97 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_planned_unit_state` | 97 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_payload` | 98 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_rows` | 98 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_bounds` | 99 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `TRAINING_PLAN_STATUSES` | 100 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_metadata` | 100 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AdaptiveDependencies` | 101 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_adaptive_changes` | 101 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PlanningChangeDependencies` | 102 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes` | 102 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes_in_db` | 102 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `JOB_STATUSES` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ITEM_STATUSES` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `aggregate_job_status` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_progress` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `decode_job_payload` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `has_active_job` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `job_dto` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `list_jobs` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_job` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `is_retryable_error` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `retry_delay` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_job_request` | 105 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTIVITY_FIELDS` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_sections_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_value_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_json_size_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_projection_meta_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_activity_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workout_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workouts_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_planned_event_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `detailed_coach_activity_value` | 119 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_DIALOGUE_INSTRUCTIONS` | 131 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `dialogue_tools` | 131 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_request` | 131 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `build_tool_contracts` | 132 | `backend/coach/tools` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `command_receipt` | 133 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `effects_from_receipts` | 133 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_resolved_receipts` | 133 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `outcome_status` | 133 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `authorized_operations` | 137 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_operation` | 137 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_scope` | 137 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `scope_values` | 137 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTION_LABELS` | 138 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_effect_label` | 138 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_failure_lines` | 138 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_language_recovery.py:163 (direkt/dynamisch unklar) |
| Importbindung | `coach_observed_sync_lines` | 138 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_header_items` | 139 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_json_bytes` | 139 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:7543 (direkt/dynamisch unklar) |
| Importbindung | `response_headers` | 139 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `session_cookies` | 139 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_audio_body` | 145 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_body` | 145 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_json` | 145 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_application_state` | 150 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_decode_payload` | 150 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_workout_library` | 150 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_manifest` | 150 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_jsonl_rows` | 150 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Globale Bindung | `Garmin` | 159 | `sync/` | P6 | offen | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4201 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `sqlite_backend` | 164 | `db/` | P1 | offen | tests/test_server.py:1198 (direkt/dynamisch unklar); tests/test_server.py:6597 (direkt/dynamisch unklar); tests/test_server.py:6610 (direkt/dynamisch unklar) |
| Globale Bindung | `SQLCIPHER_AVAILABLE` | 165 | `db/` | P1 | offen | tests/test_audit_remediation.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:315 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_server.py:2841 (direkt/dynamisch unklar); tests/test_server.py:3376 (direkt/dynamisch unklar); tests/test_server.py:6574 (direkt/dynamisch unklar) |
| Globale Bindung | `ROOT` | 171 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:6655 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6675 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PUBLIC_DIR` | 172 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2366 (direkt/dynamisch unklar); tests/test_server.py:2367 (direkt/dynamisch unklar); tests/test_server.py:2383 (direkt/dynamisch unklar); tests/test_server.py:2384 (direkt/dynamisch unklar); tests/test_server.py:7341 (direkt/dynamisch unklar); tests/test_server.py:7342 (direkt/dynamisch unklar); tests/test_server.py:7353 (direkt/dynamisch unklar); tests/test_server.py:7354 (direkt/dynamisch unklar); tests/test_server.py:7362 (direkt/dynamisch unklar); tests/test_server.py:7363 (direkt/dynamisch unklar); tests/test_server.py:7371 (direkt/dynamisch unklar); tests/test_server.py:7372 (direkt/dynamisch unklar); tests/test_server.py:7378 (direkt/dynamisch unklar); tests/test_server.py:7379 (direkt/dynamisch unklar); tests/test_server.py:7388 (direkt/dynamisch unklar); tests/test_server.py:7389 (direkt/dynamisch unklar); tests/test_server.py:7390 (direkt/dynamisch unklar); tests/test_server.py:7391 (direkt/dynamisch unklar); tests/test_server.py:7602 (direkt/dynamisch unklar); tests/test_server.py:7621 (direkt/dynamisch unklar); tests/test_server.py:8722 (direkt/dynamisch unklar); tests/test_server.py:8723 (direkt/dynamisch unklar) |
| Globale Bindung | `DATA_DIR` | 173 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_server.py:103 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:118 (direkt/dynamisch unklar); tests/test_server.py:174 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2846 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3387 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6580 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6655 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6675 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7843 (direkt/dynamisch unklar); tests/test_server.py:7913 (direkt/dynamisch unklar); tests/test_server.py:8026 (direkt/dynamisch unklar); tests/test_server.py:8055 (direkt/dynamisch unklar); tests/test_server.py:8329 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar); tests/test_server.py:94 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 174 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:104 (direkt/dynamisch unklar); tests/test_server.py:108 (direkt/dynamisch unklar); tests/test_server.py:110 (direkt/dynamisch unklar); tests/test_server.py:119 (direkt/dynamisch unklar); tests/test_server.py:2846 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3387 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6580 (Monkeypatch/getattr/sys.modules); tests/test_server.py:95 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 175 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:30 (Monkeypatch/getattr/sys.modules); tests/test_server.py:105 (direkt/dynamisch unklar); tests/test_server.py:111 (direkt/dynamisch unklar); tests/test_server.py:120 (direkt/dynamisch unklar); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7843 (direkt/dynamisch unklar); tests/test_server.py:7913 (direkt/dynamisch unklar); tests/test_server.py:8026 (direkt/dynamisch unklar); tests/test_server.py:8055 (direkt/dynamisch unklar); tests/test_server.py:8329 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar); tests/test_server.py:96 (direkt/dynamisch unklar) |
| Globale Bindung | `ASSET_INDEX_HTML` | 176 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_API_JS` | 177 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_APP_JS` | 178 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_NAVIGATION_JS` | 179 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STATE_JS` | 180 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_VIEWS_JS` | 181 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_FORMS_JS` | 182 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_COMPONENTS_JS` | 183 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STYLES_CSS` | 184 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_SERVICE_WORKER_JS` | 185 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_MANIFEST` | 186 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_LOGO` | 187 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_ICON` | 188 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_TARGETS` | 189 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `VERSIONED_STATIC_ASSETS` | 204 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_REVALIDATE_ASSETS` | 205 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_NAME` | 206 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_GARMIN_NAME` | 207 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_WELLNESS_NAME` | 208 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UTC_OFFSET_SUFFIX` | 209 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ISO_MIDNIGHT_SUFFIX` | 210 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `JSON_MEDIA_TYPE` | 211 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OCTET_STREAM_MIME` | 212 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSES_PATH` | 213 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VO2MAX_UNIT` | 214 | `performance/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_RUN_PREDICTION_SOURCE` | 215 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_STARTED_EVENT` | 216 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_COMPLETED_EVENT` | 217 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLAN_CONSTRAINTS_PREFIX` | 218 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_SCOPE_PREFIX` | 219 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LOCAL_INTERVALS_SCOPE` | 220 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `WORKDAY_TIME_LABEL` | 221 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_WORKOUT_LABEL` | 222 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `FULL_RESYNC_LABEL` | 223 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DAILY_AUTO_UPDATE_LABEL` | 224 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `APP_NAME` | 225 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UUID_PATTERN` | 226 | `http_api/` | P10 | offen | tests/test_server.py:3212 (direkt/dynamisch unklar) |
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
| Globale Bindung | `APP_VERSION` | 241 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:7335 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 242 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 243 | `http_api/` | P10 | offen | tests/test_server.py:4874 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 244 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 245 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 246 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 247 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 248 | `coach/streams.py` | P8 | offen | tests/test_server.py:1466 (direkt/dynamisch unklar); tests/test_server.py:1476 (direkt/dynamisch unklar); tests/test_server.py:1477 (direkt/dynamisch unklar) |
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
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 271 | `providers/` | P2 | offen | tests/test_server.py:5860 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 272 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 273 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 274 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 275 | `coach/` | P7 | offen | tests/test_server.py:4902 (direkt/dynamisch unklar); tests/test_server.py:5228 (direkt/dynamisch unklar); tests/test_server.py:5236 (direkt/dynamisch unklar); tests/test_server.py:5588 (direkt/dynamisch unklar); tests/test_server.py:5718 (direkt/dynamisch unklar); tests/test_server.py:5728 (direkt/dynamisch unklar); tests/test_server.py:5730 (direkt/dynamisch unklar); tests/test_server.py:5733 (direkt/dynamisch unklar); tests/test_server.py:5736 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5750 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 276 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 277 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:183 (direkt/dynamisch unklar); tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1011 (direkt/dynamisch unklar); tests/test_server.py:125 (direkt/dynamisch unklar); tests/test_server.py:1285 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1293 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1314 (direkt/dynamisch unklar); tests/test_server.py:1318 (direkt/dynamisch unklar); tests/test_server.py:1395 (direkt/dynamisch unklar); tests/test_server.py:1507 (direkt/dynamisch unklar); tests/test_server.py:156 (direkt/dynamisch unklar); tests/test_server.py:1644 (direkt/dynamisch unklar); tests/test_server.py:2529 (direkt/dynamisch unklar); tests/test_server.py:2590 (direkt/dynamisch unklar); tests/test_server.py:2603 (direkt/dynamisch unklar); tests/test_server.py:2659 (direkt/dynamisch unklar); tests/test_server.py:2682 (direkt/dynamisch unklar); tests/test_server.py:2811 (direkt/dynamisch unklar); tests/test_server.py:2824 (direkt/dynamisch unklar); tests/test_server.py:2829 (direkt/dynamisch unklar); tests/test_server.py:3027 (direkt/dynamisch unklar); tests/test_server.py:3107 (direkt/dynamisch unklar); tests/test_server.py:4630 (direkt/dynamisch unklar); tests/test_server.py:4921 (direkt/dynamisch unklar); tests/test_server.py:5053 (direkt/dynamisch unklar); tests/test_server.py:5076 (direkt/dynamisch unklar); tests/test_server.py:5099 (direkt/dynamisch unklar); tests/test_server.py:5121 (direkt/dynamisch unklar); tests/test_server.py:5135 (direkt/dynamisch unklar); tests/test_server.py:5141 (direkt/dynamisch unklar); tests/test_server.py:5158 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5488 (direkt/dynamisch unklar); tests/test_server.py:5530 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5641 (direkt/dynamisch unklar); tests/test_server.py:5883 (direkt/dynamisch unklar); tests/test_server.py:5895 (direkt/dynamisch unklar); tests/test_server.py:5914 (direkt/dynamisch unklar); tests/test_server.py:595 (direkt/dynamisch unklar); tests/test_server.py:5988 (direkt/dynamisch unklar); tests/test_server.py:6010 (direkt/dynamisch unklar); tests/test_server.py:6019 (direkt/dynamisch unklar); tests/test_server.py:6144 (direkt/dynamisch unklar); tests/test_server.py:639 (direkt/dynamisch unklar); tests/test_server.py:6436 (direkt/dynamisch unklar); tests/test_server.py:6499 (direkt/dynamisch unklar); tests/test_server.py:650 (direkt/dynamisch unklar); tests/test_server.py:6544 (direkt/dynamisch unklar); tests/test_server.py:6583 (direkt/dynamisch unklar); tests/test_server.py:6592 (direkt/dynamisch unklar); tests/test_server.py:664 (direkt/dynamisch unklar); tests/test_server.py:6768 (direkt/dynamisch unklar); tests/test_server.py:6777 (direkt/dynamisch unklar); tests/test_server.py:6787 (direkt/dynamisch unklar); tests/test_server.py:6938 (direkt/dynamisch unklar); tests/test_server.py:7732 (direkt/dynamisch unklar); tests/test_server.py:8559 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8564 (direkt/dynamisch unklar); tests/test_server.py:8700 (direkt/dynamisch unklar); tests/test_server.py:8714 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 278 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7742 (direkt/dynamisch unklar); tests/test_server.py:7754 (direkt/dynamisch unklar); tests/test_server.py:7757 (direkt/dynamisch unklar); tests/test_server.py:7770 (direkt/dynamisch unklar); tests/test_server.py:7771 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 279 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 280 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 281 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 282 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 283 | `performance/` | P3 | offen | tests/test_server.py:603 (direkt/dynamisch unklar); tests/test_server.py:609 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 284 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_LOCK` | 285 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 286 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:150 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 287 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:151 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 288 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8477 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 289 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8477 (direkt/dynamisch unklar); tests/test_server.py:8490 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 290 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 291 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 292 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 293 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 294 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 295 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:255 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 296 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:284 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 297 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 298 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 299 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 300 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 301 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 302 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 303 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 304 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5895 (direkt/dynamisch unklar); tests/test_server.py:5914 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 305 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LOCK` | 306 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7994 (direkt/dynamisch unklar); tests/test_server.py:8000 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 307 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7995 (direkt/dynamisch unklar); tests/test_server.py:7996 (direkt/dynamisch unklar); tests/test_server.py:8001 (direkt/dynamisch unklar); tests/test_server.py:8002 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 308 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 309 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 310 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 311 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Klasse | `ProviderResyncGate` | 314 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 361 | `sync/` | P6 | offen | tests/test_server.py:6622 (direkt/dynamisch unklar); tests/test_server.py:6637 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 362 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 365 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 370 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 378 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `load_local_env` | 386 | `config.py` | P1 | offen | tests/test_server.py:6667 (direkt/dynamisch unklar); tests/test_server.py:6692 (direkt/dynamisch unklar) |
| Globale Bindung | `CONFIG` | 391 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:153 (direkt/dynamisch unklar); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (direkt/dynamisch unklar); tests/test_provider_review.py:196 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:314 (direkt/dynamisch unklar); tests/test_provider_review.py:322 (direkt/dynamisch unklar); tests/test_provider_review.py:323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:100 (direkt/dynamisch unklar); tests/test_server.py:117 (direkt/dynamisch unklar); tests/test_server.py:1198 (direkt/dynamisch unklar); tests/test_server.py:1269 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1269 (direkt/dynamisch unklar); tests/test_server.py:172 (direkt/dynamisch unklar); tests/test_server.py:174 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2534 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2534 (direkt/dynamisch unklar); tests/test_server.py:2620 (direkt/dynamisch unklar); tests/test_server.py:2621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2649 (direkt/dynamisch unklar); tests/test_server.py:2650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2664 (direkt/dynamisch unklar); tests/test_server.py:2665 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2732 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2732 (direkt/dynamisch unklar); tests/test_server.py:2827 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2827 (direkt/dynamisch unklar); tests/test_server.py:2836 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2836 (direkt/dynamisch unklar); tests/test_server.py:2845 (direkt/dynamisch unklar); tests/test_server.py:2846 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3386 (direkt/dynamisch unklar); tests/test_server.py:3387 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3628 (direkt/dynamisch unklar); tests/test_server.py:3701 (direkt/dynamisch unklar); tests/test_server.py:3721 (direkt/dynamisch unklar); tests/test_server.py:3732 (direkt/dynamisch unklar); tests/test_server.py:3751 (direkt/dynamisch unklar); tests/test_server.py:3927 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3927 (direkt/dynamisch unklar); tests/test_server.py:3945 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3945 (direkt/dynamisch unklar); tests/test_server.py:3955 (direkt/dynamisch unklar); tests/test_server.py:4200 (direkt/dynamisch unklar); tests/test_server.py:4201 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4268 (direkt/dynamisch unklar); tests/test_server.py:4276 (direkt/dynamisch unklar); tests/test_server.py:4368 (direkt/dynamisch unklar); tests/test_server.py:4370 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4413 (direkt/dynamisch unklar); tests/test_server.py:4414 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4438 (direkt/dynamisch unklar); tests/test_server.py:4439 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4562 (direkt/dynamisch unklar); tests/test_server.py:4563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4577 (direkt/dynamisch unklar); tests/test_server.py:4578 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4588 (direkt/dynamisch unklar); tests/test_server.py:4589 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4603 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4603 (direkt/dynamisch unklar); tests/test_server.py:4607 (direkt/dynamisch unklar); tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4617 (direkt/dynamisch unklar); tests/test_server.py:4622 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4641 (direkt/dynamisch unklar); tests/test_server.py:4642 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4796 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4796 (direkt/dynamisch unklar); tests/test_server.py:4814 (direkt/dynamisch unklar); tests/test_server.py:4815 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4818 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4818 (direkt/dynamisch unklar); tests/test_server.py:4826 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4826 (direkt/dynamisch unklar); tests/test_server.py:4838 (direkt/dynamisch unklar); tests/test_server.py:4839 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4862 (direkt/dynamisch unklar); tests/test_server.py:4863 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4869 (direkt/dynamisch unklar); tests/test_server.py:4870 (Monkeypatch/getattr/sys.modules); tests/test_server.py:56 (direkt/dynamisch unklar); tests/test_server.py:57 (direkt/dynamisch unklar); tests/test_server.py:585 (direkt/dynamisch unklar); tests/test_server.py:586 (Monkeypatch/getattr/sys.modules); tests/test_server.py:602 (direkt/dynamisch unklar); tests/test_server.py:605 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6061 (direkt/dynamisch unklar); tests/test_server.py:6063 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6075 (direkt/dynamisch unklar); tests/test_server.py:6076 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6090 (direkt/dynamisch unklar); tests/test_server.py:6092 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6102 (direkt/dynamisch unklar); tests/test_server.py:6105 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6115 (direkt/dynamisch unklar); tests/test_server.py:6123 (Monkeypatch/getattr/sys.modules); tests/test_server.py:613 (direkt/dynamisch unklar); tests/test_server.py:6135 (direkt/dynamisch unklar); tests/test_server.py:6136 (Monkeypatch/getattr/sys.modules); tests/test_server.py:614 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6163 (direkt/dynamisch unklar); tests/test_server.py:6164 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6203 (direkt/dynamisch unklar); tests/test_server.py:6204 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6225 (direkt/dynamisch unklar); tests/test_server.py:6226 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6247 (direkt/dynamisch unklar); tests/test_server.py:6248 (Monkeypatch/getattr/sys.modules); tests/test_server.py:626 (direkt/dynamisch unklar); tests/test_server.py:6266 (direkt/dynamisch unklar); tests/test_server.py:6267 (Monkeypatch/getattr/sys.modules); tests/test_server.py:627 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6286 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6286 (direkt/dynamisch unklar); tests/test_server.py:6340 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6340 (direkt/dynamisch unklar); tests/test_server.py:6349 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6349 (direkt/dynamisch unklar); tests/test_server.py:6368 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6368 (direkt/dynamisch unklar); tests/test_server.py:6377 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6377 (direkt/dynamisch unklar); tests/test_server.py:6386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6386 (direkt/dynamisch unklar); tests/test_server.py:6394 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6394 (direkt/dynamisch unklar); tests/test_server.py:6411 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6411 (direkt/dynamisch unklar); tests/test_server.py:6455 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6455 (direkt/dynamisch unklar); tests/test_server.py:6487 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6487 (direkt/dynamisch unklar); tests/test_server.py:6533 (direkt/dynamisch unklar); tests/test_server.py:6558 (direkt/dynamisch unklar); tests/test_server.py:6566 (direkt/dynamisch unklar); tests/test_server.py:6567 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6578 (direkt/dynamisch unklar); tests/test_server.py:6580 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6625 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6625 (direkt/dynamisch unklar); tests/test_server.py:6645 (direkt/dynamisch unklar); tests/test_server.py:6646 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6823 (direkt/dynamisch unklar); tests/test_server.py:6855 (direkt/dynamisch unklar); tests/test_server.py:6893 (direkt/dynamisch unklar); tests/test_server.py:6925 (direkt/dynamisch unklar); tests/test_server.py:6941 (direkt/dynamisch unklar); tests/test_server.py:6980 (direkt/dynamisch unklar); tests/test_server.py:7013 (direkt/dynamisch unklar); tests/test_server.py:7040 (direkt/dynamisch unklar); tests/test_server.py:7323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7323 (direkt/dynamisch unklar); tests/test_server.py:7790 (direkt/dynamisch unklar); tests/test_server.py:7794 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7815 (direkt/dynamisch unklar); tests/test_server.py:7816 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7840 (direkt/dynamisch unklar); tests/test_server.py:7844 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7944 (direkt/dynamisch unklar); tests/test_server.py:7945 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7954 (direkt/dynamisch unklar); tests/test_server.py:7955 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8025 (direkt/dynamisch unklar); tests/test_server.py:8027 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8265 (direkt/dynamisch unklar); tests/test_server.py:8266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8505 (direkt/dynamisch unklar); tests/test_server.py:8506 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8575 (direkt/dynamisch unklar); tests/test_server.py:8576 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8670 (direkt/dynamisch unklar); tests/test_server.py:8677 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8688 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8744 (direkt/dynamisch unklar); tests/test_server.py:8745 (Monkeypatch/getattr/sys.modules); tests/test_server.py:93 (direkt/dynamisch unklar); tests/test_server.py:974 (direkt/dynamisch unklar); tests/test_server.py:975 (Monkeypatch/getattr/sys.modules); tests/test_server.py:983 (direkt/dynamisch unklar); tests/test_server.py:984 (Monkeypatch/getattr/sys.modules) |
| Klasse | `IntervalsClient` | 394 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:43 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:54 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:70 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:81 (direkt/dynamisch unklar); tests/test_server.py:3628 (direkt/dynamisch unklar); tests/test_server.py:3701 (direkt/dynamisch unklar); tests/test_server.py:3721 (direkt/dynamisch unklar); tests/test_server.py:3732 (direkt/dynamisch unklar); tests/test_server.py:3751 (direkt/dynamisch unklar); tests/test_server.py:3823 (direkt/dynamisch unklar); tests/test_server.py:3851 (direkt/dynamisch unklar); tests/test_server.py:3882 (direkt/dynamisch unklar); tests/test_server.py:3883 (direkt/dynamisch unklar); tests/test_server.py:3884 (direkt/dynamisch unklar); tests/test_server.py:3902 (direkt/dynamisch unklar); tests/test_server.py:3946 (direkt/dynamisch unklar); tests/test_server.py:3947 (direkt/dynamisch unklar); tests/test_server.py:3955 (direkt/dynamisch unklar); tests/test_server.py:4268 (direkt/dynamisch unklar); tests/test_server.py:4276 (direkt/dynamisch unklar); tests/test_server.py:6064 (direkt/dynamisch unklar); tests/test_server.py:6077 (direkt/dynamisch unklar); tests/test_server.py:6093 (direkt/dynamisch unklar); tests/test_server.py:6106 (direkt/dynamisch unklar); tests/test_server.py:6124 (direkt/dynamisch unklar); tests/test_server.py:615 (direkt/dynamisch unklar); tests/test_server.py:6165 (direkt/dynamisch unklar); tests/test_server.py:6166 (direkt/dynamisch unklar); tests/test_server.py:6205 (direkt/dynamisch unklar); tests/test_server.py:6227 (direkt/dynamisch unklar); tests/test_server.py:6249 (direkt/dynamisch unklar); tests/test_server.py:6250 (direkt/dynamisch unklar); tests/test_server.py:6268 (direkt/dynamisch unklar); tests/test_server.py:628 (direkt/dynamisch unklar); tests/test_server.py:6469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6532 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6557 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6822 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6854 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6892 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6924 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6940 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6979 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7012 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7039 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7712 (direkt/dynamisch unklar); tests/test_server.py:8028 (direkt/dynamisch unklar); tests/test_server.py:8029 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 697 | `observability.py` | P1 | offen | tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:23 (direkt/dynamisch unklar); tests/test_provider_review.py:31 (direkt/dynamisch unklar); tests/test_provider_review.py:40 (direkt/dynamisch unklar); tests/test_provider_review.py:42 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_server.py:7535 (direkt/dynamisch unklar); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7779 (direkt/dynamisch unklar); tests/test_server.py:7780 (direkt/dynamisch unklar); tests/test_server.py:7843 (direkt/dynamisch unklar); tests/test_server.py:7865 (direkt/dynamisch unklar); tests/test_server.py:7913 (direkt/dynamisch unklar); tests/test_server.py:7917 (direkt/dynamisch unklar); tests/test_server.py:8026 (direkt/dynamisch unklar); tests/test_server.py:8031 (direkt/dynamisch unklar); tests/test_server.py:8055 (direkt/dynamisch unklar); tests/test_server.py:8062 (direkt/dynamisch unklar); tests/test_server.py:8329 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar); tests/test_server.py:8598 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTOR` | 698 | `observability.py` | P1 | offen | tests/test_server.py:4604 (direkt/dynamisch unklar); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7805 (direkt/dynamisch unklar); tests/test_server.py:7843 (direkt/dynamisch unklar); tests/test_server.py:7913 (direkt/dynamisch unklar); tests/test_server.py:8026 (direkt/dynamisch unklar); tests/test_server.py:8055 (direkt/dynamisch unklar); tests/test_server.py:8329 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar) |
| Funktion | `external_call` | 701 | `providers/http.py` | P2 | offen | tests/test_server.py:1737 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7818 (direkt/dynamisch unklar); tests/test_server.py:7894 (direkt/dynamisch unklar); tests/test_server.py:7909 (direkt/dynamisch unklar); tests/test_server.py:8592 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 764 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 783 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 784 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 785 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 786 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 787 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 788 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 789 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 790 | `weather/` | P3 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_server.py:1186 (direkt/dynamisch unklar); tests/test_server.py:1188 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1215 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1530 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 791 | `weather/` | P3 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 792 | `history/` | P5 | offen | tests/test_server.py:4210 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 793 | `weather/` | P3 | offen | tests/test_server.py:1206 (direkt/dynamisch unklar); tests/test_server.py:1208 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 794 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 795 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 796 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 797 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 798 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 828 | `weather/` | P3 | offen | tests/test_server.py:7468 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 860 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `serialise_conversation` | 893 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8480 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 910 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:170 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:80 (direkt/dynamisch unklar); tests/test_audit_remediation.py:94 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1010 (direkt/dynamisch unklar); tests/test_server.py:1161 (direkt/dynamisch unklar); tests/test_server.py:1164 (direkt/dynamisch unklar); tests/test_server.py:1232 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1398 (direkt/dynamisch unklar); tests/test_server.py:1402 (direkt/dynamisch unklar); tests/test_server.py:1518 (direkt/dynamisch unklar); tests/test_server.py:1647 (direkt/dynamisch unklar); tests/test_server.py:2532 (direkt/dynamisch unklar); tests/test_server.py:2593 (direkt/dynamisch unklar); tests/test_server.py:2606 (direkt/dynamisch unklar); tests/test_server.py:2662 (direkt/dynamisch unklar); tests/test_server.py:2685 (direkt/dynamisch unklar); tests/test_server.py:2814 (direkt/dynamisch unklar); tests/test_server.py:3110 (direkt/dynamisch unklar); tests/test_server.py:3114 (direkt/dynamisch unklar); tests/test_server.py:5055 (direkt/dynamisch unklar); tests/test_server.py:5078 (direkt/dynamisch unklar); tests/test_server.py:5101 (direkt/dynamisch unklar); tests/test_server.py:5123 (direkt/dynamisch unklar); tests/test_server.py:5144 (direkt/dynamisch unklar); tests/test_server.py:5168 (direkt/dynamisch unklar); tests/test_server.py:5619 (direkt/dynamisch unklar); tests/test_server.py:5643 (direkt/dynamisch unklar); tests/test_server.py:5898 (direkt/dynamisch unklar); tests/test_server.py:5917 (direkt/dynamisch unklar); tests/test_server.py:7733 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 914 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 915 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 916 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 917 | `planning/` | P4 | offen | tests/test_server.py:5054 (direkt/dynamisch unklar); tests/test_server.py:5077 (direkt/dynamisch unklar); tests/test_server.py:5100 (direkt/dynamisch unklar); tests/test_server.py:5122 (direkt/dynamisch unklar); tests/test_server.py:5136 (direkt/dynamisch unklar); tests/test_server.py:5143 (direkt/dynamisch unklar); tests/test_server.py:5159 (direkt/dynamisch unklar); tests/test_server.py:5167 (direkt/dynamisch unklar); tests/test_server.py:5619 (direkt/dynamisch unklar); tests/test_server.py:5642 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 918 | `planning/` | P4 | offen | tests/test_server.py:7733 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 919 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4552 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 920 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 921 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 922 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `security_configuration_error` | 925 | `config.py` | P1 | offen | tests/test_audit_remediation.py:190 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:184 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:316 (direkt/dynamisch unklar) |
| Globale Bindung | `OPERATION_CONTEXT` | 935 | `observability.py` | P1 | offen | tests/test_server.py:8012 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 936 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:181 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 937 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_provider_review.py:49 (direkt/dynamisch unklar); tests/test_server.py:182 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETENTION_DAYS` | 939 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_MAX_ROWS` | 940 | `sync/` | P6 | offen | tests/test_server.py:8711 (direkt/dynamisch unklar); tests/test_server.py:8716 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 941 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 942 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_STALE_SECONDS` | 943 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_LABELS` | 951 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 959 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 960 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 961 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 962 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 963 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 964 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 965 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 966 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_DURATION_SECONDS` | 967 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_MAX_ENTRIES` | 968 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_STATE_KEY` | 969 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_ENTRIES_KEY` | 970 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 972 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 975 | `history/` | P5 | offen | tests/test_server.py:5588 (direkt/dynamisch unklar); tests/test_server.py:5599 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 976 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 977 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 978 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 979 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 984 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 989 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 994 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 998 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 1000 | `planning/` | P4 | offen | tests/test_server.py:363 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 1001 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 1002 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 1005 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 1016 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 1022 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 1031 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 1041 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1068 | `observability.py` | P1 | offen | tests/test_server.py:8009 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1089 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1132 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:281 (direkt/dynamisch unklar); tests/test_provider_review.py:187 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:197 (direkt/dynamisch unklar); tests/test_provider_review.py:320 (direkt/dynamisch unklar); tests/test_provider_review.py:329 (direkt/dynamisch unklar); tests/test_server.py:179 (direkt/dynamisch unklar) |
| Funktion | `database` | 1159 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:183 (direkt/dynamisch unklar); tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1011 (direkt/dynamisch unklar); tests/test_server.py:1032 (direkt/dynamisch unklar); tests/test_server.py:1041 (direkt/dynamisch unklar); tests/test_server.py:1055 (direkt/dynamisch unklar); tests/test_server.py:1067 (direkt/dynamisch unklar); tests/test_server.py:1081 (direkt/dynamisch unklar); tests/test_server.py:1090 (direkt/dynamisch unklar); tests/test_server.py:1099 (direkt/dynamisch unklar); tests/test_server.py:1106 (direkt/dynamisch unklar); tests/test_server.py:1117 (direkt/dynamisch unklar); tests/test_server.py:1128 (direkt/dynamisch unklar); tests/test_server.py:125 (direkt/dynamisch unklar); tests/test_server.py:1285 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1293 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1314 (direkt/dynamisch unklar); tests/test_server.py:1318 (direkt/dynamisch unklar); tests/test_server.py:1395 (direkt/dynamisch unklar); tests/test_server.py:1507 (direkt/dynamisch unklar); tests/test_server.py:156 (direkt/dynamisch unklar); tests/test_server.py:1644 (direkt/dynamisch unklar); tests/test_server.py:2529 (direkt/dynamisch unklar); tests/test_server.py:2590 (direkt/dynamisch unklar); tests/test_server.py:2603 (direkt/dynamisch unklar); tests/test_server.py:2659 (direkt/dynamisch unklar); tests/test_server.py:2682 (direkt/dynamisch unklar); tests/test_server.py:2811 (direkt/dynamisch unklar); tests/test_server.py:2824 (direkt/dynamisch unklar); tests/test_server.py:2829 (direkt/dynamisch unklar); tests/test_server.py:2848 (direkt/dynamisch unklar); tests/test_server.py:3027 (direkt/dynamisch unklar); tests/test_server.py:3107 (direkt/dynamisch unklar); tests/test_server.py:3395 (direkt/dynamisch unklar); tests/test_server.py:4551 (direkt/dynamisch unklar); tests/test_server.py:4630 (direkt/dynamisch unklar); tests/test_server.py:4921 (direkt/dynamisch unklar); tests/test_server.py:5053 (direkt/dynamisch unklar); tests/test_server.py:5076 (direkt/dynamisch unklar); tests/test_server.py:5099 (direkt/dynamisch unklar); tests/test_server.py:5121 (direkt/dynamisch unklar); tests/test_server.py:5135 (direkt/dynamisch unklar); tests/test_server.py:5141 (direkt/dynamisch unklar); tests/test_server.py:5158 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5488 (direkt/dynamisch unklar); tests/test_server.py:5530 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5641 (direkt/dynamisch unklar); tests/test_server.py:5883 (direkt/dynamisch unklar); tests/test_server.py:5895 (direkt/dynamisch unklar); tests/test_server.py:5914 (direkt/dynamisch unklar); tests/test_server.py:595 (direkt/dynamisch unklar); tests/test_server.py:5988 (direkt/dynamisch unklar); tests/test_server.py:6010 (direkt/dynamisch unklar); tests/test_server.py:6019 (direkt/dynamisch unklar); tests/test_server.py:6144 (direkt/dynamisch unklar); tests/test_server.py:639 (direkt/dynamisch unklar); tests/test_server.py:6436 (direkt/dynamisch unklar); tests/test_server.py:6499 (direkt/dynamisch unklar); tests/test_server.py:650 (direkt/dynamisch unklar); tests/test_server.py:6544 (direkt/dynamisch unklar); tests/test_server.py:6583 (direkt/dynamisch unklar); tests/test_server.py:6592 (direkt/dynamisch unklar); tests/test_server.py:664 (direkt/dynamisch unklar); tests/test_server.py:6768 (direkt/dynamisch unklar); tests/test_server.py:6777 (direkt/dynamisch unklar); tests/test_server.py:6787 (direkt/dynamisch unklar); tests/test_server.py:6938 (direkt/dynamisch unklar); tests/test_server.py:7732 (direkt/dynamisch unklar); tests/test_server.py:7971 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8430 (direkt/dynamisch unklar); tests/test_server.py:8564 (direkt/dynamisch unklar); tests/test_server.py:8700 (direkt/dynamisch unklar); tests/test_server.py:8714 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1165 | `db/schema.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_provider_review.py:37 (direkt/dynamisch unklar); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:112 (direkt/dynamisch unklar); tests/test_server.py:1170 (direkt/dynamisch unklar); tests/test_server.py:155 (direkt/dynamisch unklar); tests/test_server.py:178 (direkt/dynamisch unklar); tests/test_server.py:198 (direkt/dynamisch unklar); tests/test_server.py:2828 (direkt/dynamisch unklar); tests/test_server.py:2837 (direkt/dynamisch unklar); tests/test_server.py:2847 (direkt/dynamisch unklar); tests/test_server.py:3388 (direkt/dynamisch unklar); tests/test_server.py:6581 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1207 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1212 | `settings.py` | P1 | offen | tests/test_server.py:8682 (direkt/dynamisch unklar); tests/test_server.py:8698 (direkt/dynamisch unklar); tests/test_server.py:8712 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1224 | `settings.py` | P1 | offen | tests/test_server.py:8683 (direkt/dynamisch unklar); tests/test_server.py:8699 (direkt/dynamisch unklar); tests/test_server.py:8713 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1258 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1273 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1287 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1296 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1310 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1323 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1333 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1342 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1352 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1359 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1384 | `sync/` | P6 | offen | tests/test_audit_remediation.py:278 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:208 (direkt/dynamisch unklar); tests/test_server.py:210 (direkt/dynamisch unklar); tests/test_server.py:214 (direkt/dynamisch unklar); tests/test_server.py:225 (direkt/dynamisch unklar); tests/test_server.py:258 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1393 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:142 (direkt/dynamisch unklar); tests/test_provider_review.py:179 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1399 | `sync/` | P6 | offen | tests/test_server.py:975 (Monkeypatch/getattr/sys.modules); tests/test_server.py:984 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1404 | `sync/` | P6 | offen | tests/test_server.py:606 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1427 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1435 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1444 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1462 | `sync/` | P6 | offen | tests/test_server.py:618 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1489 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1498 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1505 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1515 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 1540 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 1554 | `sync/` | P6 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:203 (direkt/dynamisch unklar); tests/test_server.py:220 (direkt/dynamisch unklar); tests/test_server.py:247 (direkt/dynamisch unklar); tests/test_server.py:344 (Monkeypatch/getattr/sys.modules); tests/test_server.py:431 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4894 (direkt/dynamisch unklar); tests/test_server.py:4898 (direkt/dynamisch unklar); tests/test_server.py:527 (Monkeypatch/getattr/sys.modules); tests/test_server.py:587 (direkt/dynamisch unklar); tests/test_server.py:590 (direkt/dynamisch unklar); tests/test_server.py:605 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6343 (direkt/dynamisch unklar); tests/test_server.py:6352 (direkt/dynamisch unklar); tests/test_server.py:6371 (direkt/dynamisch unklar); tests/test_server.py:6380 (direkt/dynamisch unklar); tests/test_server.py:867 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8692 (direkt/dynamisch unklar); tests/test_server.py:893 (Monkeypatch/getattr/sys.modules); tests/test_server.py:938 (Monkeypatch/getattr/sys.modules); tests/test_server.py:986 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 1581 | `sync/` | P6 | offen | tests/test_server.py:209 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 1601 | `sync/` | P6 | offen | tests/test_audit_remediation.py:274 (direkt/dynamisch unklar); tests/test_audit_remediation.py:279 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:154 (direkt/dynamisch unklar); tests/test_server.py:206 (direkt/dynamisch unklar); tests/test_server.py:211 (direkt/dynamisch unklar); tests/test_server.py:221 (direkt/dynamisch unklar); tests/test_server.py:254 (direkt/dynamisch unklar); tests/test_server.py:6344 (direkt/dynamisch unklar); tests/test_server.py:6353 (direkt/dynamisch unklar); tests/test_server.py:6372 (direkt/dynamisch unklar); tests/test_server.py:6381 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 1622 | `sync/` | P6 | offen | tests/test_audit_remediation.py:241 (direkt/dynamisch unklar); tests/test_audit_remediation.py:276 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 1660 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 1666 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 1677 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 1697 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 1712 | `runtime/` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 1729 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 1742 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 1751 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 1758 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 1775 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 1787 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 1799 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:138 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:167 (Monkeypatch/getattr/sys.modules); tests/test_server.py:212 (Monkeypatch/getattr/sys.modules); tests/test_server.py:223 (Monkeypatch/getattr/sys.modules); tests/test_server.py:236 (direkt/dynamisch unklar); tests/test_server.py:256 (Monkeypatch/getattr/sys.modules); tests/test_server.py:553 (direkt/dynamisch unklar); tests/test_server.py:554 (direkt/dynamisch unklar); tests/test_server.py:566 (direkt/dynamisch unklar); tests/test_server.py:579 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 1822 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 1831 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 1851 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 1871 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 1889 | `sync/` | P6 | offen | tests/test_provider_review.py:139 (direkt/dynamisch unklar); tests/test_provider_review.py:168 (direkt/dynamisch unklar); tests/test_server.py:213 (direkt/dynamisch unklar); tests/test_server.py:224 (direkt/dynamisch unklar); tests/test_server.py:257 (direkt/dynamisch unklar); tests/test_server.py:6344 (direkt/dynamisch unklar); tests/test_server.py:6353 (direkt/dynamisch unklar); tests/test_server.py:6372 (direkt/dynamisch unklar); tests/test_server.py:6381 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 1899 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 1914 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `resolve_sync_job` | 1926 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_scheduled_provider_retry_at` | 1949 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_inputs` | 1968 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_last_good_state` | 2002 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_fallback_error_code` | 2012 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_error_code` | 2016 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_status` | 2024 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `provider_freshness_state` | 2045 | `settings.py` | P1 | offen | tests/test_server.py:6141 (direkt/dynamisch unklar); tests/test_server.py:8679 (direkt/dynamisch unklar); tests/test_server.py:8684 (direkt/dynamisch unklar); tests/test_server.py:8689 (direkt/dynamisch unklar); tests/test_server.py:8696 (direkt/dynamisch unklar); tests/test_server.py:8706 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 2086 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 2100 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 2111 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 2135 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 2140 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 2152 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 2162 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 2179 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2218 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2250 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3155 (direkt/dynamisch unklar); tests/test_server.py:5571 (direkt/dynamisch unklar); tests/test_server.py:5660 (direkt/dynamisch unklar); tests/test_server.py:5709 (direkt/dynamisch unklar); tests/test_server.py:8633 (direkt/dynamisch unklar); tests/test_server.py:8653 (direkt/dynamisch unklar); tests/test_server.py:8662 (direkt/dynamisch unklar); tests/test_server.py:8665 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2261 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2273 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2287 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2303 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8642 (direkt/dynamisch unklar); tests/test_server.py:8648 (direkt/dynamisch unklar); tests/test_server.py:8654 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2341 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2361 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2371 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2396 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2417 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2427 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2436 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2462 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2478 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2498 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2507 | `history/` | P5 | offen | tests/test_server.py:3162 (direkt/dynamisch unklar); tests/test_server.py:5578 (direkt/dynamisch unklar); tests/test_server.py:5713 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2522 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:237 (direkt/dynamisch unklar); tests/test_audit_remediation.py:287 (direkt/dynamisch unklar); tests/test_audit_remediation.py:288 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar); tests/test_provider_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:1188 (direkt/dynamisch unklar); tests/test_server.py:1208 (direkt/dynamisch unklar); tests/test_server.py:1215 (direkt/dynamisch unklar); tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:199 (direkt/dynamisch unklar); tests/test_server.py:200 (direkt/dynamisch unklar); tests/test_server.py:2838 (direkt/dynamisch unklar); tests/test_server.py:2839 (direkt/dynamisch unklar); tests/test_server.py:4161 (direkt/dynamisch unklar); tests/test_server.py:4162 (direkt/dynamisch unklar); tests/test_server.py:4445 (direkt/dynamisch unklar); tests/test_server.py:4568 (direkt/dynamisch unklar); tests/test_server.py:6098 (direkt/dynamisch unklar); tests/test_server.py:6110 (direkt/dynamisch unklar); tests/test_server.py:6111 (direkt/dynamisch unklar); tests/test_server.py:6214 (direkt/dynamisch unklar); tests/test_server.py:6233 (direkt/dynamisch unklar); tests/test_server.py:6237 (direkt/dynamisch unklar); tests/test_server.py:6572 (direkt/dynamisch unklar); tests/test_server.py:6591 (direkt/dynamisch unklar); tests/test_server.py:6649 (direkt/dynamisch unklar); tests/test_server.py:7744 (direkt/dynamisch unklar); tests/test_server.py:7762 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 2529 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 2530 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 2531 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 2532 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_CALENDAR_WINDOW_DAYS` | 2533 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2641 (direkt/dynamisch unklar) |
| Globale Bindung | `ICAL_MAX_RECURRENCE_COUNT` | 2534 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_MAX_RECURRENCE_PERIODS` | 2535 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 2536 | `planning/` | P4 | offen | tests/test_server.py:2704 (direkt/dynamisch unklar); tests/test_server.py:2714 (direkt/dynamisch unklar); tests/test_server.py:2739 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 2537 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 2538 | `planning/` | P4 | offen | tests/test_server.py:2316 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 2539 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 2542 | `planning/` | P4 | offen | tests/test_server.py:3646 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 2543 | `planning/` | P4 | offen | tests/test_server.py:3647 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 2544 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 2545 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 2546 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 2547 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 2548 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 2549 | `coach/` | P7 | offen | tests/test_server.py:5349 (direkt/dynamisch unklar); tests/test_server.py:5360 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 2550 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 2563 | `sync/` | P6 | offen | tests/test_server.py:6035 (direkt/dynamisch unklar); tests/test_server.py:6037 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 2574 | `sync/` | P6 | offen | tests/test_server.py:6034 (direkt/dynamisch unklar); tests/test_server.py:6036 (direkt/dynamisch unklar); tests/test_server.py:6062 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 2586 | `sync/` | P6 | offen | tests/test_server.py:6038 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 2597 | `settings.py` | P1 | offen | tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:223 (direkt/dynamisch unklar); tests/test_provider_review.py:247 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 2602 | `settings.py` | P1 | offen | tests/test_provider_review.py:210 (direkt/dynamisch unklar); tests/test_provider_review.py:211 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 2608 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:326 (direkt/dynamisch unklar); tests/test_server.py:1186 (direkt/dynamisch unklar); tests/test_server.py:1206 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1391 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1393 (direkt/dynamisch unklar); tests/test_server.py:1394 (direkt/dynamisch unklar); tests/test_server.py:1486 (direkt/dynamisch unklar); tests/test_server.py:1498 (direkt/dynamisch unklar); tests/test_server.py:1530 (direkt/dynamisch unklar); tests/test_server.py:1638 (direkt/dynamisch unklar); tests/test_server.py:1853 (direkt/dynamisch unklar); tests/test_server.py:1854 (direkt/dynamisch unklar); tests/test_server.py:1855 (direkt/dynamisch unklar); tests/test_server.py:1856 (direkt/dynamisch unklar); tests/test_server.py:1857 (direkt/dynamisch unklar); tests/test_server.py:196 (direkt/dynamisch unklar); tests/test_server.py:197 (direkt/dynamisch unklar); tests/test_server.py:2834 (direkt/dynamisch unklar); tests/test_server.py:2835 (direkt/dynamisch unklar); tests/test_server.py:3259 (direkt/dynamisch unklar); tests/test_server.py:3283 (direkt/dynamisch unklar); tests/test_server.py:3294 (direkt/dynamisch unklar); tests/test_server.py:3342 (direkt/dynamisch unklar); tests/test_server.py:3449 (direkt/dynamisch unklar); tests/test_server.py:3481 (direkt/dynamisch unklar); tests/test_server.py:3500 (direkt/dynamisch unklar); tests/test_server.py:3541 (direkt/dynamisch unklar); tests/test_server.py:3561 (direkt/dynamisch unklar); tests/test_server.py:4211 (direkt/dynamisch unklar); tests/test_server.py:4217 (direkt/dynamisch unklar); tests/test_server.py:4501 (direkt/dynamisch unklar); tests/test_server.py:4525 (direkt/dynamisch unklar); tests/test_server.py:4538 (direkt/dynamisch unklar); tests/test_server.py:4618 (direkt/dynamisch unklar); tests/test_server.py:4640 (direkt/dynamisch unklar); tests/test_server.py:5416 (direkt/dynamisch unklar); tests/test_server.py:5452 (direkt/dynamisch unklar); tests/test_server.py:5947 (direkt/dynamisch unklar); tests/test_server.py:6103 (direkt/dynamisch unklar); tests/test_server.py:6565 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6640 (direkt/dynamisch unklar); tests/test_server.py:6641 (direkt/dynamisch unklar); tests/test_server.py:7723 (direkt/dynamisch unklar); tests/test_server.py:7724 (direkt/dynamisch unklar); tests/test_server.py:7741 (direkt/dynamisch unklar); tests/test_server.py:7756 (direkt/dynamisch unklar); tests/test_server.py:7830 (direkt/dynamisch unklar); tests/test_server.py:7946 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar); tests/test_server.py:8504 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS` | 2616 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:382 (direkt/dynamisch unklar); tests/test_server.py:4590 (direkt/dynamisch unklar); tests/test_server.py:4591 (direkt/dynamisch unklar); tests/test_server.py:4592 (direkt/dynamisch unklar); tests/test_server.py:4596 (direkt/dynamisch unklar); tests/test_server.py:4597 (direkt/dynamisch unklar); tests/test_server.py:4598 (direkt/dynamisch unklar); tests/test_server.py:4599 (direkt/dynamisch unklar); tests/test_server.py:5428 (direkt/dynamisch unklar); tests/test_server.py:5429 (direkt/dynamisch unklar); tests/test_server.py:5430 (direkt/dynamisch unklar); tests/test_server.py:5432 (direkt/dynamisch unklar); tests/test_server.py:5435 (direkt/dynamisch unklar); tests/test_server.py:5436 (direkt/dynamisch unklar); tests/test_server.py:5437 (direkt/dynamisch unklar); tests/test_server.py:5439 (direkt/dynamisch unklar); tests/test_server.py:5442 (direkt/dynamisch unklar); tests/test_server.py:5444 (direkt/dynamisch unklar); tests/test_server.py:5447 (direkt/dynamisch unklar); tests/test_server.py:5449 (direkt/dynamisch unklar); tests/test_server.py:5451 (direkt/dynamisch unklar); tests/test_server.py:5453 (direkt/dynamisch unklar); tests/test_server.py:5456 (direkt/dynamisch unklar) |
| Funktion | `_safe_diagnostic_context` | 2619 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_mapping_shape` | 2631 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_sequence_shape` | 2643 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_response_shape` | 2650 | `observability.py` | P1 | offen | tests/test_server.py:8583 (direkt/dynamisch unklar); tests/test_server.py:8588 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_response` | 2667 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_diagnostic_error` | 2672 | `observability.py` | P1 | offen | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 2690 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 2705 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_capture_state` | 2722 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_capture_status` | 2730 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7908 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_entries` | 2752 | `observability.py` | P1 | offen | tests/test_server.py:7901 (direkt/dynamisch unklar); tests/test_server.py:8270 (direkt/dynamisch unklar) |
| Funktion | `set_diagnostic_capture` | 2762 | `observability.py` | P1 | offen | tests/test_server.py:7887 (direkt/dynamisch unklar); tests/test_server.py:7907 (direkt/dynamisch unklar); tests/test_server.py:8264 (direkt/dynamisch unklar) |
| Funktion | `capture_diagnostic_event` | 2777 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 2791 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:217 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar); tests/test_server.py:5421 (direkt/dynamisch unklar); tests/test_server.py:5423 (direkt/dynamisch unklar); tests/test_server.py:6650 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 2799 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 2803 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4154 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 2811 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 2823 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 2838 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 2848 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 2859 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 2868 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 2883 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 2897 | `activities/` | P3 | offen | tests/test_server.py:3612 (direkt/dynamisch unklar); tests/test_server.py:3620 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 2909 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 2925 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 2940 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7632 (direkt/dynamisch unklar); tests/test_server.py:7643 (direkt/dynamisch unklar); tests/test_server.py:7651 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 2947 | `sync/` | P6 | offen | tests/test_server.py:3425 (direkt/dynamisch unklar); tests/test_server.py:7633 (direkt/dynamisch unklar); tests/test_server.py:7659 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 2954 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 2969 | `activities/` | P3 | offen | tests/test_server.py:7698 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 2992 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 3005 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 3023 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 3041 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7674 (direkt/dynamisch unklar); tests/test_server.py:7687 (direkt/dynamisch unklar); tests/test_server.py:7699 (direkt/dynamisch unklar); tests/test_server.py:7711 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 3056 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3428 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 3071 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 3084 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 3096 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 3099 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 3103 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 3109 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 3114 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 3123 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3336 (direkt/dynamisch unklar); tests/test_server.py:3337 (direkt/dynamisch unklar); tests/test_server.py:3338 (direkt/dynamisch unklar); tests/test_server.py:3339 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 3142 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 3155 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 3159 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 3177 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 3191 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 3207 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 3213 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 3221 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 3234 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 3247 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 3254 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 3272 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 3277 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 3303 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 3313 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 3322 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3443 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 3332 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3347 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3356 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3361 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3369 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3383 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3394 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3413 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3424 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3441 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3465 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3474 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3485 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3504 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:292 (direkt/dynamisch unklar); tests/test_provider_review.py:307 (direkt/dynamisch unklar); tests/test_server.py:3311 (direkt/dynamisch unklar); tests/test_server.py:3368 (direkt/dynamisch unklar); tests/test_server.py:3401 (direkt/dynamisch unklar); tests/test_server.py:3428 (direkt/dynamisch unklar); tests/test_server.py:3435 (direkt/dynamisch unklar); tests/test_server.py:3475 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3526 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 3541 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 3546 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 3562 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:302 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 3580 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 3599 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 3628 | `planning/` | P4 | offen | tests/test_server.py:3254 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 3645 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 3653 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 3681 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 3688 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 3712 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 3721 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 3738 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 3754 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 3759 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4111 (direkt/dynamisch unklar); tests/test_server.py:4115 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 3760 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 3763 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4114 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 3771 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4113 (direkt/dynamisch unklar); tests/test_server.py:4118 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 3780 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4112 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 3793 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4117 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 3798 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 3820 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 3830 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 3834 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4166 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 3849 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 3850 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 3853 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 3872 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 3886 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 3897 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4156 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 3908 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 3916 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 3921 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 3925 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 3943 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 3953 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 3957 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4142 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 3977 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 3988 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 4006 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:4121 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 4043 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 4048 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4210 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 4056 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 4069 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 4093 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 4122 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 4146 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4202 (direkt/dynamisch unklar); tests/test_server.py:4203 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 4159 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 4171 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 4201 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 4230 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 4237 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 4296 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 4319 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:242 (direkt/dynamisch unklar); tests/test_server.py:234 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4155 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8578 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4361 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:359 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4368 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4379 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:4209 (direkt/dynamisch unklar); tests/test_server.py:4221 (direkt/dynamisch unklar); tests/test_server.py:7831 (direkt/dynamisch unklar); tests/test_server.py:8579 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4419 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:280 (direkt/dynamisch unklar); tests/test_server.py:3274 (direkt/dynamisch unklar); tests/test_server.py:3288 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4442 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1691 (direkt/dynamisch unklar); tests/test_server.py:1723 (direkt/dynamisch unklar); tests/test_server.py:4522 (direkt/dynamisch unklar); tests/test_server.py:4523 (direkt/dynamisch unklar); tests/test_server.py:4524 (direkt/dynamisch unklar); tests/test_server.py:5239 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4449 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4456 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4459 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4471 | `athlete/` | P3 | offen | tests/test_server.py:1137 (direkt/dynamisch unklar); tests/test_server.py:1600 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4480 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1610 (direkt/dynamisch unklar); tests/test_server.py:6756 (direkt/dynamisch unklar); tests/test_server.py:8646 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4489 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:144 (direkt/dynamisch unklar); tests/test_audit_remediation.py:76 (direkt/dynamisch unklar); tests/test_audit_remediation.py:79 (direkt/dynamisch unklar); tests/test_audit_remediation.py:87 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1160 (direkt/dynamisch unklar); tests/test_server.py:1169 (direkt/dynamisch unklar); tests/test_server.py:1185 (direkt/dynamisch unklar); tests/test_server.py:1187 (direkt/dynamisch unklar); tests/test_server.py:1191 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1207 (direkt/dynamisch unklar); tests/test_server.py:1211 (direkt/dynamisch unklar); tests/test_server.py:1219 (direkt/dynamisch unklar); tests/test_server.py:1226 (direkt/dynamisch unklar); tests/test_server.py:1245 (direkt/dynamisch unklar); tests/test_server.py:149 (direkt/dynamisch unklar); tests/test_server.py:1512 (direkt/dynamisch unklar); tests/test_server.py:1529 (direkt/dynamisch unklar); tests/test_server.py:1572 (direkt/dynamisch unklar); tests/test_server.py:1593 (direkt/dynamisch unklar); tests/test_server.py:1595 (direkt/dynamisch unklar); tests/test_server.py:1606 (direkt/dynamisch unklar); tests/test_server.py:2501 (direkt/dynamisch unklar); tests/test_server.py:6709 (direkt/dynamisch unklar); tests/test_server.py:6737 (direkt/dynamisch unklar); tests/test_server.py:7306 (direkt/dynamisch unklar); tests/test_server.py:7451 (direkt/dynamisch unklar); tests/test_server.py:8631 (direkt/dynamisch unklar); tests/test_server.py:8632 (direkt/dynamisch unklar); tests/test_server.py:8661 (direkt/dynamisch unklar); tests/test_server.py:8678 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4503 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4513 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4520 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4523 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 4535 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 4547 | `athlete/` | P3 | offen | tests/test_server.py:1617 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 4567 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2713 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 4572 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1580 (direkt/dynamisch unklar); tests/test_server.py:1589 (direkt/dynamisch unklar); tests/test_server.py:1619 (direkt/dynamisch unklar); tests/test_server.py:1623 (direkt/dynamisch unklar); tests/test_server.py:1637 (direkt/dynamisch unklar); tests/test_server.py:1668 (direkt/dynamisch unklar); tests/test_server.py:2702 (direkt/dynamisch unklar); tests/test_server.py:2723 (direkt/dynamisch unklar); tests/test_server.py:2749 (direkt/dynamisch unklar); tests/test_server.py:2768 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 4580 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 4603 | `athlete/` | P3 | offen | tests/test_server.py:1587 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 4613 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 4620 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 4634 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2363 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 4639 | `activities/` | P3 | offen | tests/test_server.py:2360 (direkt/dynamisch unklar); tests/test_server.py:2362 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 4651 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2330 (direkt/dynamisch unklar); tests/test_server.py:2343 (direkt/dynamisch unklar); tests/test_server.py:2353 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 4668 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 4675 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 4689 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 4701 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 4723 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 4735 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 4749 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 4755 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3210 (direkt/dynamisch unklar); tests/test_server.py:3214 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 4765 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3212 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 4772 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 4785 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3196 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 4806 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:45 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:58 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:6459 (direkt/dynamisch unklar); tests/test_server.py:646 (direkt/dynamisch unklar); tests/test_server.py:6541 (direkt/dynamisch unklar); tests/test_server.py:656 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:6830 (direkt/dynamisch unklar); tests/test_server.py:6864 (direkt/dynamisch unklar); tests/test_server.py:6901 (direkt/dynamisch unklar); tests/test_server.py:6948 (direkt/dynamisch unklar); tests/test_server.py:6985 (direkt/dynamisch unklar); tests/test_server.py:6993 (direkt/dynamisch unklar); tests/test_server.py:7020 (direkt/dynamisch unklar); tests/test_server.py:7048 (direkt/dynamisch unklar) |
| Funktion | `_resolve_calendar_addresses` | 4811 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2566 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_calendar_feed_request` | 4826 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_remaining` | 4849 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_fetch_calendar_address` | 4856 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_failure_log` | 4891 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `fetch_calendar_feed` | 4906 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2536 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2571 (direkt/dynamisch unklar); tests/test_server.py:2584 (direkt/dynamisch unklar); tests/test_server.py:2621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2665 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_ical_temporal_value` | 4961 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_TRAINING_MARKER` | 4991 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_INTENSITY_MARKER` | 4992 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_SHORT_ONLY_MARKER` | 4993 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_TRAINING_MARKERS` | 4994 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_description_contains` | 4997 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_impact` | 5001 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_relevant` | 5006 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_no_intensity` | 5012 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_short_only` | 5017 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_DAY_NUMBERS` | 5022 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_values` | 5025 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_integer` | 5040 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_byday` | 5057 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_bydays` | 5071 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_until` | 5088 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rrule` | 5097 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_shift_local` | 5137 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekday_ordinal` | 5141 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_byday` | 5145 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_date_filters` | 5161 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_dates` | 5174 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_apply_bysetpos` | 5188 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_recurrence_start` | 5200 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_record` | 5205 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_daily_recurrence_starts` | 5224 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_candidate_starts` | 5246 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_recurrence_starts` | 5258 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_period` | 5284 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_candidates` | 5294 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_marker` | 5299 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_first_period_index` | 5303 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_recurrence_starts` | 5312 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_starts` | 5337 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_duration` | 5347 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_occurrence_overlaps_window` | 5358 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rule_starts` | 5363 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rdates` | 5376 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_instances` | 5383 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_calendar_window` | 5400 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_property_parameters` | 5408 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_dates` | 5419 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_temporal_property` | 5434 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_id` | 5444 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_event_property` | 5451 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_append_event` | 5472 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_skip_nested_event_line` | 5481 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_parsed_events` | 5489 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_exception_starts` | 5513 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_event_instances` | 5521 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_expanded_events` | 5535 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `parse_ical_calendar` | 5548 | `providers/calendar.py` | P2 | offen | tests/test_audit_remediation.py:160 (direkt/dynamisch unklar); tests/test_audit_remediation.py:164 (direkt/dynamisch unklar); tests/test_server.py:2394 (direkt/dynamisch unklar); tests/test_server.py:2425 (direkt/dynamisch unklar); tests/test_server.py:2453 (direkt/dynamisch unklar); tests/test_server.py:2459 (direkt/dynamisch unklar); tests/test_server.py:2466 (direkt/dynamisch unklar); tests/test_server.py:2473 (direkt/dynamisch unklar); tests/test_server.py:2478 (direkt/dynamisch unklar); tests/test_server.py:2482 (direkt/dynamisch unklar); tests/test_server.py:2493 (direkt/dynamisch unklar); tests/test_server.py:2508 (direkt/dynamisch unklar); tests/test_server.py:2521 (direkt/dynamisch unklar); tests/test_server.py:2525 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_url` | 5554 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2544 (direkt/dynamisch unklar); tests/test_server.py:2553 (direkt/dynamisch unklar); tests/test_server.py:2672 (direkt/dynamisch unklar); tests/test_server.py:2674 (direkt/dynamisch unklar); tests/test_server.py:7822 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_external_calendar_events` | 5570 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2539 (direkt/dynamisch unklar); tests/test_server.py:2595 (direkt/dynamisch unklar); tests/test_server.py:2636 (direkt/dynamisch unklar); tests/test_server.py:2655 (direkt/dynamisch unklar); tests/test_server.py:2668 (direkt/dynamisch unklar); tests/test_server.py:3116 (direkt/dynamisch unklar); tests/test_server.py:3118 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 5581 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2631 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 5596 | `sync/` | P6 | offen | tests/test_server.py:2538 (direkt/dynamisch unklar); tests/test_server.py:2626 (direkt/dynamisch unklar); tests/test_server.py:2651 (direkt/dynamisch unklar); tests/test_server.py:2667 (direkt/dynamisch unklar); tests/test_server.py:7826 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 5642 | `providers/calendar.py` | P2 | offen | tests/test_audit_remediation.py:163 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 5657 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 5661 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 5665 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 5671 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 5677 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 5685 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 5703 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 5720 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 5747 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 5754 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 5768 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 5800 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 5809 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 5820 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 5839 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 5851 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 5857 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 5870 | `performance/` | P3 | offen | tests/test_server.py:4212 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 5882 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 5886 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 5896 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 5905 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 5915 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 5926 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 5935 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 5955 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 5969 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1649 (direkt/dynamisch unklar); tests/test_server.py:3118 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 5993 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 6002 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 6014 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 6027 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 6042 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 6048 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 6059 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 6067 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 6078 | `coach/context.py` | P7 | offen | tests/test_server.py:1214 (direkt/dynamisch unklar); tests/test_server.py:3606 (direkt/dynamisch unklar); tests/test_server.py:6331 (direkt/dynamisch unklar); tests/test_server.py:6359 (direkt/dynamisch unklar); tests/test_server.py:6403 (direkt/dynamisch unklar); tests/test_server.py:6421 (direkt/dynamisch unklar); tests/test_server.py:6430 (direkt/dynamisch unklar); tests/test_server.py:6494 (direkt/dynamisch unklar); tests/test_server.py:6717 (direkt/dynamisch unklar); tests/test_server.py:6784 (direkt/dynamisch unklar); tests/test_server.py:6834 (direkt/dynamisch unklar); tests/test_server.py:6870 (direkt/dynamisch unklar); tests/test_server.py:6909 (direkt/dynamisch unklar); tests/test_server.py:6992 (direkt/dynamisch unklar); tests/test_server.py:6998 (direkt/dynamisch unklar); tests/test_server.py:7024 (direkt/dynamisch unklar); tests/test_server.py:7043 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 6095 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 6117 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 6129 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 6130 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 6135 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 6145 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 6163 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 6175 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 6188 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 6200 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 6219 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:39 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1073 (direkt/dynamisch unklar); tests/test_server.py:418 (direkt/dynamisch unklar); tests/test_server.py:636 (direkt/dynamisch unklar); tests/test_server.py:6415 (direkt/dynamisch unklar); tests/test_server.py:6441 (direkt/dynamisch unklar); tests/test_server.py:6753 (direkt/dynamisch unklar); tests/test_server.py:6758 (direkt/dynamisch unklar); tests/test_server.py:6792 (direkt/dynamisch unklar); tests/test_server.py:6933 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 6227 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:51 (direkt/dynamisch unklar); tests/test_audit_remediation.py:63 (direkt/dynamisch unklar); tests/test_server.py:6773 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 6257 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 6278 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 6301 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 6316 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 6326 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 6332 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3189 (direkt/dynamisch unklar); tests/test_server.py:3190 (direkt/dynamisch unklar); tests/test_server.py:3191 (direkt/dynamisch unklar); tests/test_server.py:3192 (direkt/dynamisch unklar); tests/test_server.py:3193 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 6337 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 6352 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_server.py:6439 (direkt/dynamisch unklar); tests/test_server.py:6771 (direkt/dynamisch unklar); tests/test_server.py:6786 (direkt/dynamisch unklar); tests/test_server.py:6863 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 6356 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3218 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 6376 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3206 (direkt/dynamisch unklar); tests/test_server.py:3207 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 6392 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 6402 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3244 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 6409 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3245 (direkt/dynamisch unklar); tests/test_server.py:3246 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 6415 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3230 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 6443 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 6449 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 6458 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 6468 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6928 (direkt/dynamisch unklar); tests/test_server.py:6945 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 6508 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 6522 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 6535 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 6561 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 6587 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 6595 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 6603 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 6607 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 6645 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 6653 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 6660 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 6675 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 6687 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 6699 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 6706 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 6710 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 6743 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 6766 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 6785 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 6802 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 6810 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 6840 | `sync/` | P6 | offen | tests/test_audit_remediation.py:44 (direkt/dynamisch unklar); tests/test_audit_remediation.py:55 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_audit_remediation.py:71 (direkt/dynamisch unklar); tests/test_server.py:6414 (direkt/dynamisch unklar); tests/test_server.py:6422 (direkt/dynamisch unklar); tests/test_server.py:6458 (direkt/dynamisch unklar); tests/test_server.py:6628 (direkt/dynamisch unklar); tests/test_server.py:6825 (direkt/dynamisch unklar); tests/test_server.py:6857 (direkt/dynamisch unklar); tests/test_server.py:6858 (direkt/dynamisch unklar); tests/test_server.py:6895 (direkt/dynamisch unklar); tests/test_server.py:6927 (direkt/dynamisch unklar); tests/test_server.py:6943 (direkt/dynamisch unklar); tests/test_server.py:6946 (direkt/dynamisch unklar); tests/test_server.py:6982 (direkt/dynamisch unklar); tests/test_server.py:7015 (direkt/dynamisch unklar); tests/test_server.py:7042 (direkt/dynamisch unklar); tests/test_server.py:7044 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_RATE_LIMIT_HEADERS` | 6896 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_STATUS_KEY` | 6905 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `GEMINI_STATUS_KEY` | 6906 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 6907 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `_retry_after_seconds` | 6910 | `providers/http.py` | P2 | offen | tests/test_server.py:8149 (direkt/dynamisch unklar) |
| Funktion | `_safe_openai_error_token` | 6924 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_diagnostic_details` | 6932 | `observability.py` | P1 | offen | tests/test_server.py:8212 (direkt/dynamisch unklar); tests/test_server.py:8235 (direkt/dynamisch unklar) |
| Funktion | `_openai_error_tokens` | 6955 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_invalid_input_state` | 6965 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_conversation_error` | 6973 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_billing_error` | 6984 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_error_reason` | 6995 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_details` | 7015 | `providers/` | P2 | offen | tests/test_server.py:8137 (direkt/dynamisch unklar); tests/test_server.py:8142 (direkt/dynamisch unklar); tests/test_server.py:8210 (direkt/dynamisch unklar); tests/test_server.py:8233 (direkt/dynamisch unklar); tests/test_server.py:8250 (direkt/dynamisch unklar) |
| Funktion | `safe_openai_log_reason` | 7031 | `observability.py` | P1 | offen | tests/test_server.py:8181 (direkt/dynamisch unklar); tests/test_server.py:8182 (direkt/dynamisch unklar) |
| Funktion | `_provider_error_payload` | 7054 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_tokens` | 7063 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_reason` | 7071 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_error_details` | 7085 | `providers/` | P2 | offen | tests/test_server.py:4648 (direkt/dynamisch unklar); tests/test_server.py:4650 (direkt/dynamisch unklar); tests/test_server.py:4651 (direkt/dynamisch unklar) |
| Funktion | `record_openai_status` | 7091 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_success` | 7106 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_rate_limits` | 7116 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_body` | 7128 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 7136 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 7144 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 7156 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 7161 | `coach/context.py` | P7 | offen | tests/test_server.py:7940 (direkt/dynamisch unklar) |
| Funktion | `_read_http_error_body` | 7171 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_urlopen_interruptibly` | 7182 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_body` | 7209 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_parts` | 7217 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_http_request_started` | 7251 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_http_response` | 7264 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 7279 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 7320 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 7339 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 7389 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 7424 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 7429 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 7457 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1737 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4370 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4439 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4578 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4668 (direkt/dynamisch unklar); tests/test_server.py:4709 (direkt/dynamisch unklar); tests/test_server.py:4746 (direkt/dynamisch unklar); tests/test_server.py:4779 (direkt/dynamisch unklar); tests/test_server.py:4839 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7452 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7846 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7882 (direkt/dynamisch unklar); tests/test_server.py:7916 (direkt/dynamisch unklar); tests/test_server.py:7933 (direkt/dynamisch unklar); tests/test_server.py:8057 (direkt/dynamisch unklar); tests/test_server.py:8093 (direkt/dynamisch unklar); tests/test_server.py:8121 (direkt/dynamisch unklar); tests/test_server.py:8162 (direkt/dynamisch unklar); tests/test_server.py:8506 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 7492 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 7504 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 7513 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 7521 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 7525 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 7531 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 7543 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 7548 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 7574 | `weather/` | P3 | offen | tests/test_server.py:1148 (direkt/dynamisch unklar); tests/test_server.py:1154 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 7584 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 7608 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 7623 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 7642 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 7657 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 7671 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 7692 | `weather/` | P3 | offen | tests/test_server.py:7495 (direkt/dynamisch unklar); tests/test_server.py:7502 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 7739 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 7755 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 7765 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 7786 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 7806 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 7810 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 7833 | `weather/` | P3 | offen | tests/test_audit_remediation.py:106 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:81 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1166 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1192 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1220 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1234 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1253 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1520 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1536 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 7845 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 7856 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 7883 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 7891 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 7904 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 7940 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 7959 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 7965 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 7987 | `weather/` | P3 | offen | tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_audit_remediation.py:147 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:82 (direkt/dynamisch unklar); tests/test_server.py:1167 (direkt/dynamisch unklar); tests/test_server.py:1168 (direkt/dynamisch unklar); tests/test_server.py:1254 (direkt/dynamisch unklar); tests/test_server.py:1255 (direkt/dynamisch unklar); tests/test_server.py:1256 (direkt/dynamisch unklar); tests/test_server.py:1546 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2982 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7457 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 8005 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 8023 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 8038 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 8045 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 8061 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 8089 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 8102 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 8122 | `sync/` | P6 | offen | tests/test_audit_remediation.py:148 (direkt/dynamisch unklar); tests/test_server.py:1235 (direkt/dynamisch unklar); tests/test_server.py:1236 (direkt/dynamisch unklar); tests/test_server.py:1237 (direkt/dynamisch unklar); tests/test_server.py:1523 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 8138 | `weather/` | P3 | offen | tests/test_server.py:7469 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 8150 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 8163 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 8168 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 8173 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 8177 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 8181 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 8189 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 8205 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 8224 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 8228 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 8237 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 8249 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 8270 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 8297 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 8312 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 8325 | `planning/` | P4 | offen | tests/test_server.py:2929 (direkt/dynamisch unklar); tests/test_server.py:2931 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 8363 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 8384 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 8404 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 8422 | `planning/` | P4 | offen | tests/test_server.py:2894 (direkt/dynamisch unklar); tests/test_server.py:2954 (direkt/dynamisch unklar); tests/test_server.py:2993 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 8432 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:2955 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 8456 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 8476 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 8482 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 8505 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 8515 | `planning/` | P4 | offen | tests/test_server.py:2854 (direkt/dynamisch unklar); tests/test_server.py:3571 (direkt/dynamisch unklar); tests/test_server.py:6700 (direkt/dynamisch unklar); tests/test_server.py:7068 (direkt/dynamisch unklar); tests/test_server.py:7097 (direkt/dynamisch unklar); tests/test_server.py:7226 (direkt/dynamisch unklar); tests/test_server.py:7250 (direkt/dynamisch unklar); tests/test_server.py:7271 (direkt/dynamisch unklar); tests/test_server.py:7287 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 8553 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 8554 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 8559 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 8562 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 8571 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 8575 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 8584 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 8609 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 8616 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 8627 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3801 (direkt/dynamisch unklar); tests/test_server.py:3818 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 8641 | `planning/` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:3083 (direkt/dynamisch unklar); tests/test_server.py:3175 (direkt/dynamisch unklar); tests/test_server.py:3251 (direkt/dynamisch unklar); tests/test_server.py:3837 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 8664 | `planning/` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 8677 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3763 (direkt/dynamisch unklar); tests/test_server.py:3813 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 8704 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 8714 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 8724 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 8731 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 8749 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 8759 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 8772 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 8785 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 8800 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 8809 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:3586 (direkt/dynamisch unklar); tests/test_server.py:3591 (direkt/dynamisch unklar); tests/test_server.py:3592 (direkt/dynamisch unklar); tests/test_server.py:3602 (direkt/dynamisch unklar); tests/test_server.py:3607 (direkt/dynamisch unklar); tests/test_server.py:5042 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 8824 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 8837 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 8861 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 8872 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 8887 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1542 (direkt/dynamisch unklar); tests/test_server.py:1559 (direkt/dynamisch unklar); tests/test_server.py:2599 (direkt/dynamisch unklar); tests/test_server.py:2678 (direkt/dynamisch unklar); tests/test_server.py:2698 (direkt/dynamisch unklar); tests/test_server.py:2745 (direkt/dynamisch unklar); tests/test_server.py:2764 (direkt/dynamisch unklar); tests/test_server.py:2775 (direkt/dynamisch unklar); tests/test_server.py:2807 (direkt/dynamisch unklar); tests/test_server.py:360 (direkt/dynamisch unklar); tests/test_server.py:3785 (direkt/dynamisch unklar); tests/test_server.py:3870 (direkt/dynamisch unklar); tests/test_server.py:3898 (direkt/dynamisch unklar); tests/test_server.py:3919 (direkt/dynamisch unklar); tests/test_server.py:3921 (direkt/dynamisch unklar); tests/test_server.py:3928 (direkt/dynamisch unklar); tests/test_server.py:5553 (direkt/dynamisch unklar); tests/test_server.py:5563 (direkt/dynamisch unklar); tests/test_server.py:5591 (direkt/dynamisch unklar); tests/test_server.py:5836 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6302 (direkt/dynamisch unklar); tests/test_server.py:773 (direkt/dynamisch unklar); tests/test_server.py:806 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 8904 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5557 (direkt/dynamisch unklar); tests/test_server.py:5568 (direkt/dynamisch unklar); tests/test_server.py:5584 (direkt/dynamisch unklar); tests/test_server.py:5596 (direkt/dynamisch unklar); tests/test_server.py:5612 (direkt/dynamisch unklar); tests/test_server.py:5635 (direkt/dynamisch unklar); tests/test_server.py:5657 (direkt/dynamisch unklar); tests/test_server.py:800 (direkt/dynamisch unklar); tests/test_server.py:828 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 8912 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 8920 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 8925 | `planning/` | P4 | offen | tests/test_server.py:5559 (direkt/dynamisch unklar); tests/test_server.py:5569 (direkt/dynamisch unklar); tests/test_server.py:812 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 8942 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 8947 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 8959 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 8977 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 9006 | `planning/` | P4 | offen | tests/test_audit_remediation.py:224 (direkt/dynamisch unklar); tests/test_server.py:1573 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 9018 | `planning/` | P4 | offen | tests/test_server.py:2719 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 9035 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7734 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 9052 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 9077 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 9091 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 9100 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 9118 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 9132 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 9140 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 9158 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 9167 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 9181 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 9196 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 9213 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 9230 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 9254 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 9286 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 9312 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 9333 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 9341 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 9360 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 9383 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1550 (direkt/dynamisch unklar); tests/test_server.py:1567 (direkt/dynamisch unklar); tests/test_server.py:2608 (direkt/dynamisch unklar); tests/test_server.py:2687 (direkt/dynamisch unklar); tests/test_server.py:2703 (direkt/dynamisch unklar); tests/test_server.py:2717 (direkt/dynamisch unklar); tests/test_server.py:2724 (direkt/dynamisch unklar); tests/test_server.py:2750 (direkt/dynamisch unklar); tests/test_server.py:2769 (direkt/dynamisch unklar); tests/test_server.py:2779 (direkt/dynamisch unklar); tests/test_server.py:2816 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 9414 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 9425 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 9441 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 9456 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 9466 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 9505 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 9520 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 9528 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 9550 | `planning/` | P4 | offen | tests/test_audit_remediation.py:228 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2708 (direkt/dynamisch unklar); tests/test_server.py:2735 (direkt/dynamisch unklar); tests/test_server.py:2754 (direkt/dynamisch unklar); tests/test_server.py:2759 (direkt/dynamisch unklar); tests/test_server.py:2771 (direkt/dynamisch unklar); tests/test_server.py:2780 (direkt/dynamisch unklar); tests/test_server.py:2783 (direkt/dynamisch unklar); tests/test_server.py:2817 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 9580 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 9604 | `planning/` | P4 | offen | tests/test_server.py:1574 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 9608 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 9616 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 9632 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 9645 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 9650 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 9655 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 9664 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 9673 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 9695 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 9701 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 9705 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 9718 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 9732 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 9738 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 9751 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 9764 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 9785 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 9801 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 9811 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 9827 | `planning/` | P4 | offen | tests/test_server.py:2795 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 9850 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 9866 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 9869 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 9893 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 9902 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:3002 (direkt/dynamisch unklar); tests/test_server.py:3124 (direkt/dynamisch unklar); tests/test_server.py:3145 (direkt/dynamisch unklar); tests/test_server.py:330 (direkt/dynamisch unklar); tests/test_server.py:3598 (direkt/dynamisch unklar); tests/test_server.py:4905 (direkt/dynamisch unklar); tests/test_server.py:4927 (direkt/dynamisch unklar); tests/test_server.py:4983 (direkt/dynamisch unklar); tests/test_server.py:5000 (direkt/dynamisch unklar); tests/test_server.py:5018 (direkt/dynamisch unklar); tests/test_server.py:5036 (direkt/dynamisch unklar); tests/test_server.py:5057 (direkt/dynamisch unklar); tests/test_server.py:5080 (direkt/dynamisch unklar); tests/test_server.py:5125 (direkt/dynamisch unklar); tests/test_server.py:5147 (direkt/dynamisch unklar); tests/test_server.py:5170 (direkt/dynamisch unklar); tests/test_server.py:5186 (direkt/dynamisch unklar); tests/test_server.py:5203 (direkt/dynamisch unklar); tests/test_server.py:5266 (direkt/dynamisch unklar); tests/test_server.py:5328 (direkt/dynamisch unklar); tests/test_server.py:5337 (direkt/dynamisch unklar); tests/test_server.py:5495 (direkt/dynamisch unklar); tests/test_server.py:5526 (direkt/dynamisch unklar); tests/test_server.py:5689 (direkt/dynamisch unklar); tests/test_server.py:5719 (direkt/dynamisch unklar); tests/test_server.py:5737 (direkt/dynamisch unklar); tests/test_server.py:5742 (direkt/dynamisch unklar); tests/test_server.py:5751 (direkt/dynamisch unklar); tests/test_server.py:5755 (direkt/dynamisch unklar); tests/test_server.py:5760 (direkt/dynamisch unklar); tests/test_server.py:5769 (direkt/dynamisch unklar); tests/test_server.py:5788 (direkt/dynamisch unklar); tests/test_server.py:5791 (direkt/dynamisch unklar); tests/test_server.py:5817 (direkt/dynamisch unklar); tests/test_server.py:660 (direkt/dynamisch unklar); tests/test_server.py:683 (direkt/dynamisch unklar); tests/test_server.py:700 (direkt/dynamisch unklar); tests/test_server.py:726 (direkt/dynamisch unklar); tests/test_server.py:730 (direkt/dynamisch unklar); tests/test_server.py:7330 (direkt/dynamisch unklar); tests/test_server.py:833 (direkt/dynamisch unklar); tests/test_server.py:853 (direkt/dynamisch unklar); tests/test_server.py:857 (direkt/dynamisch unklar); tests/test_server.py:880 (direkt/dynamisch unklar); tests/test_server.py:928 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 9920 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2711 (direkt/dynamisch unklar); tests/test_server.py:2712 (direkt/dynamisch unklar); tests/test_server.py:2720 (direkt/dynamisch unklar); tests/test_server.py:2785 (direkt/dynamisch unklar); tests/test_server.py:3056 (direkt/dynamisch unklar); tests/test_server.py:3066 (direkt/dynamisch unklar); tests/test_server.py:3069 (direkt/dynamisch unklar); tests/test_server.py:3080 (direkt/dynamisch unklar); tests/test_server.py:3096 (direkt/dynamisch unklar); tests/test_server.py:3167 (direkt/dynamisch unklar); tests/test_server.py:3908 (direkt/dynamisch unklar); tests/test_server.py:3912 (direkt/dynamisch unklar); tests/test_server.py:3920 (direkt/dynamisch unklar); tests/test_server.py:3924 (direkt/dynamisch unklar); tests/test_server.py:4918 (direkt/dynamisch unklar); tests/test_server.py:4944 (direkt/dynamisch unklar); tests/test_server.py:4961 (direkt/dynamisch unklar); tests/test_server.py:4995 (direkt/dynamisch unklar); tests/test_server.py:5013 (direkt/dynamisch unklar); tests/test_server.py:5031 (direkt/dynamisch unklar); tests/test_server.py:5070 (direkt/dynamisch unklar); tests/test_server.py:5094 (direkt/dynamisch unklar); tests/test_server.py:5116 (direkt/dynamisch unklar); tests/test_server.py:5183 (direkt/dynamisch unklar); tests/test_server.py:5199 (direkt/dynamisch unklar); tests/test_server.py:5220 (direkt/dynamisch unklar); tests/test_server.py:5520 (direkt/dynamisch unklar); tests/test_server.py:5521 (direkt/dynamisch unklar); tests/test_server.py:5610 (direkt/dynamisch unklar); tests/test_server.py:5684 (direkt/dynamisch unklar); tests/test_server.py:5812 (direkt/dynamisch unklar); tests/test_server.py:5842 (direkt/dynamisch unklar); tests/test_server.py:6212 (direkt/dynamisch unklar); tests/test_server.py:723 (direkt/dynamisch unklar); tests/test_server.py:751 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 9932 | `planning/` | P4 | offen | tests/test_server.py:3668 (direkt/dynamisch unklar); tests/test_server.py:3879 (direkt/dynamisch unklar); tests/test_server.py:3941 (direkt/dynamisch unklar); tests/test_server.py:6241 (direkt/dynamisch unklar); tests/test_server.py:6278 (direkt/dynamisch unklar); tests/test_server.py:6322 (direkt/dynamisch unklar); tests/test_server.py:6481 (direkt/dynamisch unklar); tests/test_server.py:8652 (direkt/dynamisch unklar); tests/test_server.py:8742 (direkt/dynamisch unklar); tests/test_server.py:8743 (direkt/dynamisch unklar); tests/test_server.py:951 (direkt/dynamisch unklar); tests/test_server.py:954 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 9960 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3867 (direkt/dynamisch unklar); tests/test_server.py:493 (direkt/dynamisch unklar); tests/test_server.py:687 (direkt/dynamisch unklar); tests/test_server.py:905 (direkt/dynamisch unklar); tests/test_server.py:925 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 9983 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 9998 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 10015 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 10030 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 10053 | `planning/` | P4 | offen | tests/test_server.py:1386 (direkt/dynamisch unklar); tests/test_server.py:1703 (direkt/dynamisch unklar); tests/test_server.py:3653 (direkt/dynamisch unklar); tests/test_server.py:3659 (direkt/dynamisch unklar); tests/test_server.py:3683 (direkt/dynamisch unklar); tests/test_server.py:4292 (direkt/dynamisch unklar); tests/test_server.py:4308 (direkt/dynamisch unklar); tests/test_server.py:4326 (direkt/dynamisch unklar); tests/test_server.py:4341 (direkt/dynamisch unklar); tests/test_server.py:6295 (direkt/dynamisch unklar); tests/test_server.py:6495 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 10078 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3664 (direkt/dynamisch unklar); tests/test_server.py:3673 (direkt/dynamisch unklar); tests/test_server.py:3675 (direkt/dynamisch unklar); tests/test_server.py:3676 (direkt/dynamisch unklar); tests/test_server.py:3678 (direkt/dynamisch unklar); tests/test_server.py:3680 (direkt/dynamisch unklar); tests/test_server.py:3888 (direkt/dynamisch unklar); tests/test_server.py:3951 (direkt/dynamisch unklar); tests/test_server.py:4296 (direkt/dynamisch unklar); tests/test_server.py:4304 (direkt/dynamisch unklar); tests/test_server.py:4312 (direkt/dynamisch unklar); tests/test_server.py:4322 (direkt/dynamisch unklar); tests/test_server.py:4330 (direkt/dynamisch unklar); tests/test_server.py:4338 (direkt/dynamisch unklar); tests/test_server.py:4345 (direkt/dynamisch unklar); tests/test_server.py:6170 (direkt/dynamisch unklar); tests/test_server.py:6259 (direkt/dynamisch unklar); tests/test_server.py:6312 (direkt/dynamisch unklar); tests/test_server.py:6547 (direkt/dynamisch unklar); tests/test_server.py:8658 (direkt/dynamisch unklar); tests/test_server.py:921 (direkt/dynamisch unklar); tests/test_server.py:922 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 10085 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 10102 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 10103 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 10104 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 10105 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 10108 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 10115 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 10120 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 10130 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 10137 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1682 (direkt/dynamisch unklar); tests/test_server.py:1683 (direkt/dynamisch unklar); tests/test_server.py:1684 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 10164 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_audit_remediation.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1692 (direkt/dynamisch unklar); tests/test_server.py:1693 (direkt/dynamisch unklar); tests/test_server.py:1698 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 10196 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1707 (direkt/dynamisch unklar); tests/test_server.py:1708 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 10224 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1858 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 10245 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 10265 | `activities/` | P3 | offen | tests/test_server.py:489 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 10306 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 10311 | `planning/` | P4 | offen | tests/test_server.py:2694 (direkt/dynamisch unklar); tests/test_server.py:2707 (direkt/dynamisch unklar); tests/test_server.py:2710 (direkt/dynamisch unklar); tests/test_server.py:2758 (direkt/dynamisch unklar); tests/test_server.py:2784 (direkt/dynamisch unklar); tests/test_server.py:2818 (direkt/dynamisch unklar); tests/test_server.py:2821 (direkt/dynamisch unklar); tests/test_server.py:2981 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3031 (direkt/dynamisch unklar); tests/test_server.py:3048 (direkt/dynamisch unklar); tests/test_server.py:3142 (direkt/dynamisch unklar); tests/test_server.py:3787 (direkt/dynamisch unklar); tests/test_server.py:3876 (direkt/dynamisch unklar); tests/test_server.py:3934 (direkt/dynamisch unklar); tests/test_server.py:4305 (direkt/dynamisch unklar); tests/test_server.py:4323 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 10316 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 10323 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 10334 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 10346 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 10371 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 10387 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 10395 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 10409 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 10421 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:3016 (direkt/dynamisch unklar); tests/test_server.py:3031 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 10440 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 10445 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 10462 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 10476 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 10483 | `calendar/` | P3 | offen | tests/test_server.py:3116 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 10498 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 10511 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 10524 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 10581 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 10598 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 10638 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 10645 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 10653 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 10661 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 10674 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 10684 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 10696 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 10725 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 10735 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 10757 | `planning/` | P4 | offen | tests/test_server.py:266 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 10774 | `sync/` | P6 | offen | tests/test_server.py:3907 (direkt/dynamisch unklar); tests/test_server.py:3911 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 10779 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 10797 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 10804 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 10813 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 10828 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 10833 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 10839 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 10847 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 10859 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 10868 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 10885 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 10905 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 10908 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 10921 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 10933 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 10956 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 10976 | `planning/` | P4 | offen | tests/test_server.py:6065 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6094 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6107 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6127 (direkt/dynamisch unklar); tests/test_server.py:616 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6206 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6230 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6271 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6289 (direkt/dynamisch unklar); tests/test_server.py:629 (Monkeypatch/getattr/sys.modules) |
| Funktion | `plan_library_workout_remote` | 11017 | `planning/` | P4 | offen | tests/test_server.py:6470 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 11021 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 11042 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 11057 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 11063 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 11070 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 11085 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 11100 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 11110 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 11116 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 11131 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 11139 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1390 (direkt/dynamisch unklar); tests/test_server.py:3671 (direkt/dynamisch unklar); tests/test_server.py:3674 (direkt/dynamisch unklar); tests/test_server.py:3677 (direkt/dynamisch unklar); tests/test_server.py:3679 (direkt/dynamisch unklar); tests/test_server.py:3685 (direkt/dynamisch unklar); tests/test_server.py:3687 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 11163 | `planning/` | P4 | offen | tests/test_server.py:6485 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 11182 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 11198 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 11210 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 11224 | `calendar/` | P3 | offen | tests/test_server.py:7947 (direkt/dynamisch unklar); tests/test_server.py:7957 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 11259 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 11289 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 11307 | `sync/` | P6 | offen | tests/test_server.py:1859 (direkt/dynamisch unklar); tests/test_server.py:2104 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 11311 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 11326 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 11345 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 11358 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 11372 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 11391 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 11404 | `sync/` | P6 | offen | tests/test_server.py:3886 (direkt/dynamisch unklar); tests/test_server.py:3892 (direkt/dynamisch unklar); tests/test_server.py:3948 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 11419 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 11427 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 11451 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 11456 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 11479 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 11486 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 11511 | `planning/` | P4 | offen | tests/test_server.py:4298 (direkt/dynamisch unklar); tests/test_server.py:4318 (direkt/dynamisch unklar); tests/test_server.py:4333 (direkt/dynamisch unklar); tests/test_server.py:4347 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 11525 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 11534 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 11545 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 11554 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 11566 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 11579 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 11583 | `sync/` | P6 | offen | tests/test_server.py:6534 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8750 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 11596 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 11609 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 11613 | `sync/` | P6 | offen | tests/test_server.py:267 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 11632 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 11647 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 11662 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 11678 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 11691 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 11708 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 11719 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 11735 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 11753 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 11772 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 11795 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 11810 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 11819 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 11840 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 11858 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 11882 | `planning/` | P4 | offen | tests/test_server.py:2752 (direkt/dynamisch unklar); tests/test_server.py:2770 (direkt/dynamisch unklar); tests/test_server.py:3053 (direkt/dynamisch unklar); tests/test_server.py:3067 (direkt/dynamisch unklar); tests/test_server.py:3097 (direkt/dynamisch unklar); tests/test_server.py:3129 (direkt/dynamisch unklar); tests/test_server.py:3136 (direkt/dynamisch unklar); tests/test_server.py:3138 (direkt/dynamisch unklar); tests/test_server.py:3140 (direkt/dynamisch unklar); tests/test_server.py:3150 (direkt/dynamisch unklar); tests/test_server.py:3152 (direkt/dynamisch unklar); tests/test_server.py:3601 (direkt/dynamisch unklar); tests/test_server.py:3875 (direkt/dynamisch unklar); tests/test_server.py:3923 (direkt/dynamisch unklar); tests/test_server.py:5041 (direkt/dynamisch unklar); tests/test_server.py:5741 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 11908 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 11919 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 11930 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 11940 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 11946 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 11957 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 11969 | `planning/` | P4 | offen | tests/test_server.py:3099 (direkt/dynamisch unklar); tests/test_server.py:3102 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 11987 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:92 (direkt/dynamisch unklar); tests/test_server.py:1650 (direkt/dynamisch unklar); tests/test_server.py:1651 (direkt/dynamisch unklar); tests/test_server.py:2980 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5420 (direkt/dynamisch unklar); tests/test_server.py:5422 (direkt/dynamisch unklar); tests/test_server.py:6539 (direkt/dynamisch unklar); tests/test_server.py:6562 (direkt/dynamisch unklar); tests/test_server.py:7719 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 11992 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:110 (direkt/dynamisch unklar); tests/test_provider_review.py:230 (direkt/dynamisch unklar); tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_provider_review.py:63 (direkt/dynamisch unklar); tests/test_provider_review.py:87 (direkt/dynamisch unklar); tests/test_server.py:1418 (direkt/dynamisch unklar); tests/test_server.py:1630 (direkt/dynamisch unklar); tests/test_server.py:1667 (direkt/dynamisch unklar); tests/test_server.py:1675 (direkt/dynamisch unklar); tests/test_server.py:1715 (direkt/dynamisch unklar); tests/test_server.py:2323 (direkt/dynamisch unklar); tests/test_server.py:2348 (direkt/dynamisch unklar); tests/test_server.py:3627 (direkt/dynamisch unklar); tests/test_server.py:3692 (direkt/dynamisch unklar); tests/test_server.py:4314 (direkt/dynamisch unklar); tests/test_server.py:444 (direkt/dynamisch unklar); tests/test_server.py:5374 (direkt/dynamisch unklar); tests/test_server.py:5415 (direkt/dynamisch unklar); tests/test_server.py:6551 (direkt/dynamisch unklar); tests/test_server.py:7332 (direkt/dynamisch unklar); tests/test_server.py:7710 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 12002 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 12028 | `sync/` | P6 | offen | tests/test_server.py:1003 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 12053 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 12058 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 12068 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 12076 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 12107 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 12129 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 12140 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 12154 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 12176 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 12193 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 12227 | `planning/` | P4 | offen | tests/test_server.py:3044 (direkt/dynamisch unklar); tests/test_server.py:3046 (direkt/dynamisch unklar); tests/test_server.py:3054 (direkt/dynamisch unklar); tests/test_server.py:3065 (direkt/dynamisch unklar); tests/test_server.py:3068 (direkt/dynamisch unklar); tests/test_server.py:3076 (direkt/dynamisch unklar); tests/test_server.py:3095 (direkt/dynamisch unklar); tests/test_server.py:3098 (direkt/dynamisch unklar); tests/test_server.py:3101 (direkt/dynamisch unklar); tests/test_server.py:3585 (direkt/dynamisch unklar); tests/test_server.py:3590 (direkt/dynamisch unklar); tests/test_server.py:5669 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 12275 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 12291 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 12303 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 12315 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 12320 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 12330 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 12337 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 12344 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 12355 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 12370 | `sync/` | P6 | offen | tests/test_server.py:6397 (direkt/dynamisch unklar); tests/test_server.py:6535 (direkt/dynamisch unklar); tests/test_server.py:6561 (direkt/dynamisch unklar); tests/test_server.py:6571 (direkt/dynamisch unklar); tests/test_server.py:6647 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 12405 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 12420 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 12449 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 12478 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 12498 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 12515 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 12572 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 12587 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 12598 | `sync/` | P6 | offen | tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:574 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6066 (direkt/dynamisch unklar); tests/test_server.py:6081 (direkt/dynamisch unklar); tests/test_server.py:6096 (direkt/dynamisch unklar); tests/test_server.py:6109 (direkt/dynamisch unklar); tests/test_server.py:6138 (direkt/dynamisch unklar); tests/test_server.py:6167 (direkt/dynamisch unklar); tests/test_server.py:619 (direkt/dynamisch unklar); tests/test_server.py:6207 (direkt/dynamisch unklar); tests/test_server.py:6208 (direkt/dynamisch unklar); tests/test_server.py:6232 (direkt/dynamisch unklar); tests/test_server.py:6234 (direkt/dynamisch unklar); tests/test_server.py:6254 (direkt/dynamisch unklar); tests/test_server.py:6272 (direkt/dynamisch unklar); tests/test_server.py:632 (direkt/dynamisch unklar); tests/test_server.py:6389 (direkt/dynamisch unklar); tests/test_server.py:6490 (direkt/dynamisch unklar); tests/test_server.py:7763 (direkt/dynamisch unklar); tests/test_server.py:8030 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 12632 | `performance/` | P3 | offen | tests/test_provider_review.py:77 (direkt/dynamisch unklar); tests/test_server.py:550 (Monkeypatch/getattr/sys.modules); tests/test_server.py:563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7324 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 12656 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 12663 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 12670 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 12688 | `activities/` | P3 | offen | tests/test_server.py:5288 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 12700 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 12717 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 12730 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 12747 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 12768 | `performance/` | P3 | offen | tests/test_server.py:7221 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 12777 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 12789 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 12805 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 12820 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 12856 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 12866 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 12880 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 12896 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 12913 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 12923 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 12934 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 12948 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 12960 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 12965 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 12997 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 13006 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 13012 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 13019 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 13033 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 13046 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 13050 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 13079 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 13086 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 13123 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 13143 | `performance/` | P3 | offen | tests/test_server.py:3346 (direkt/dynamisch unklar); tests/test_server.py:3355 (direkt/dynamisch unklar); tests/test_server.py:3463 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 13172 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 13186 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 13202 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 13210 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 13220 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 13247 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 13262 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 13285 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 13303 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 13335 | `activities/` | P3 | offen | tests/test_server.py:7120 (direkt/dynamisch unklar); tests/test_server.py:7142 (direkt/dynamisch unklar); tests/test_server.py:7148 (direkt/dynamisch unklar); tests/test_server.py:7157 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 13380 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 13413 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 13434 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 13446 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 13466 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 13479 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 13510 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 13540 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 13551 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 13594 | `performance/` | P3 | offen | tests/test_provider_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:3486 (direkt/dynamisch unklar); tests/test_server.py:3516 (direkt/dynamisch unklar); tests/test_server.py:3545 (direkt/dynamisch unklar); tests/test_server.py:3566 (direkt/dynamisch unklar); tests/test_server.py:3578 (direkt/dynamisch unklar); tests/test_server.py:7059 (direkt/dynamisch unklar); tests/test_server.py:7081 (direkt/dynamisch unklar); tests/test_server.py:7108 (direkt/dynamisch unklar); tests/test_server.py:7177 (direkt/dynamisch unklar); tests/test_server.py:7191 (direkt/dynamisch unklar); tests/test_server.py:7207 (direkt/dynamisch unklar); tests/test_server.py:7238 (direkt/dynamisch unklar); tests/test_server.py:7259 (direkt/dynamisch unklar); tests/test_server.py:7281 (direkt/dynamisch unklar); tests/test_server.py:7301 (direkt/dynamisch unklar); tests/test_server.py:7307 (direkt/dynamisch unklar); tests/test_server.py:7311 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 13665 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 13679 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 13683 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 13687 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 13692 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 13696 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 13700 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 13704 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 13708 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 13727 | `coach/context.py` | P7 | offen | tests/test_server.py:5278 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 13746 | `coach/context.py` | P7 | offen | tests/test_server.py:5270 (direkt/dynamisch unklar); tests/test_server.py:5307 (direkt/dynamisch unklar); tests/test_server.py:5308 (direkt/dynamisch unklar); tests/test_server.py:5329 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 13792 | `coach/context.py` | P7 | offen | tests/test_server.py:1537 (direkt/dynamisch unklar); tests/test_server.py:1611 (direkt/dynamisch unklar); tests/test_server.py:2337 (direkt/dynamisch unklar); tests/test_server.py:3299 (direkt/dynamisch unklar); tests/test_server.py:5350 (direkt/dynamisch unklar); tests/test_server.py:5356 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6732 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 13857 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 13875 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 13885 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 13902 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:248 (direkt/dynamisch unklar); tests/test_provider_review.py:282 (direkt/dynamisch unklar); tests/test_server.py:3665 (direkt/dynamisch unklar); tests/test_server.py:5346 (direkt/dynamisch unklar); tests/test_server.py:5357 (direkt/dynamisch unklar); tests/test_server.py:5358 (direkt/dynamisch unklar); tests/test_server.py:5375 (direkt/dynamisch unklar); tests/test_server.py:5386 (direkt/dynamisch unklar); tests/test_server.py:5418 (direkt/dynamisch unklar); tests/test_server.py:6710 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 13942 | `coach/context.py` | P7 | offen | tests/test_server.py:5240 (direkt/dynamisch unklar); tests/test_server.py:5380 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 13998 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 14028 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_openai_usage_summary_unlocked` | 14038 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_usage_summary` | 14061 | `providers/` | P2 | offen | tests/test_server.py:8094 (direkt/dynamisch unklar); tests/test_server.py:8124 (direkt/dynamisch unklar); tests/test_server.py:8316 (direkt/dynamisch unklar); tests/test_server.py:8326 (direkt/dynamisch unklar); tests/test_server.py:8350 (direkt/dynamisch unklar); tests/test_server.py:8373 (direkt/dynamisch unklar); tests/test_server.py:8517 (direkt/dynamisch unklar); tests/test_server.py:8555 (direkt/dynamisch unklar) |
| Funktion | `_record_openai_usage_unlocked` | 14069 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_usage` | 14098 | `providers/` | P2 | offen | tests/test_server.py:5860 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8512 (direkt/dynamisch unklar); tests/test_server.py:8553 (direkt/dynamisch unklar) |
| Funktion | `_validate_openai_response` | 14105 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8494 (direkt/dynamisch unklar); tests/test_server.py:8497 (direkt/dynamisch unklar); tests/test_server.py:8500 (direkt/dynamisch unklar) |
| Funktion | `openai_endpoint` | 14127 | `providers/` | P2 | offen | tests/test_server.py:4816 (direkt/dynamisch unklar); tests/test_server.py:4817 (direkt/dynamisch unklar); tests/test_server.py:4819 (direkt/dynamisch unklar); tests/test_server.py:4828 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 14144 | `providers/` | P2 | offen | tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4840 (direkt/dynamisch unklar); tests/test_server.py:5463 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5472 (direkt/dynamisch unklar); tests/test_server.py:6065 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8195 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8507 (direkt/dynamisch unklar) |
| Funktion | `multipart_form_data` | 14168 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VOICE_AUDIO_TYPES` | 14193 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `normalized_audio_type` | 14205 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `transcribe_audio` | 14209 | `providers/` | P2 | offen | tests/test_server.py:4579 (direkt/dynamisch unklar); tests/test_server.py:4799 (direkt/dynamisch unklar); tests/test_server.py:4872 (direkt/dynamisch unklar); tests/test_server.py:4874 (direkt/dynamisch unklar) |
| Funktion | `_provider_usage_summary` | 14261 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_usage_summary` | 14278 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_status` | 14283 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_usage` | 14289 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_content_has_function_response` | 14308 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 14313 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 14320 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 14331 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 14347 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 14359 | `providers/` | P2 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4502 (direkt/dynamisch unklar); tests/test_server.py:4634 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 14367 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 14379 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 14395 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 14411 | `providers/` | P2 | offen | tests/test_server.py:4513 (direkt/dynamisch unklar); tests/test_server.py:4518 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 14433 | `providers/` | P2 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_text` | 14455 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_tools` | 14459 | `providers/` | P2 | offen | tests/test_server.py:4674 (direkt/dynamisch unklar) |
| Funktion | `_gemini_request_payload` | 14463 | `providers/` | P2 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4530 (direkt/dynamisch unklar); tests/test_server.py:4543 (direkt/dynamisch unklar); tests/test_server.py:4613 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 14559 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 14578 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 14617 | `providers/` | P2 | offen | tests/test_server.py:4371 (direkt/dynamisch unklar); tests/test_server.py:4373 (direkt/dynamisch unklar); tests/test_server.py:4440 (direkt/dynamisch unklar); tests/test_server.py:4443 (direkt/dynamisch unklar); tests/test_server.py:4565 (direkt/dynamisch unklar); tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 14624 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `request_ai_provider` | 14765 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 14770 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4610 (direkt/dynamisch unklar); tests/test_server.py:5464 (direkt/dynamisch unklar); tests/test_server.py:5855 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8196 (direkt/dynamisch unklar) |
| Funktion | `_openai_response_id` | 14795 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `retrieve_openai_response` | 14802 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 14817 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 14835 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5861 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 14872 | `coach/context.py` | P7 | offen | tests/test_server.py:6121 (direkt/dynamisch unklar) |
| Funktion | `_notify_openai_stream_response_id` | 14877 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_forward_openai_stream_delta` | 14890 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_stream_final_response` | 14898 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_consume_openai_sse_event` | 14905 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_read_openai_stream_response` | 14924 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_openai_stream_failure` | 14960 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_capture_openai_stream_failure` | 14978 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 14992 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 15004 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 15015 | `providers/` | P2 | offen | tests/test_server.py:8176 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 15032 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 15048 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 15063 | `providers/` | P2 | offen | tests/test_server.py:4864 (direkt/dynamisch unklar); tests/test_server.py:8268 (direkt/dynamisch unklar); tests/test_server.py:8309 (direkt/dynamisch unklar); tests/test_server.py:8323 (direkt/dynamisch unklar); tests/test_server.py:8347 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8378 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 15140 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4415 (direkt/dynamisch unklar); tests/test_server.py:5961 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8379 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 15166 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 15185 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 15198 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 15216 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 15229 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 15235 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 15243 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:292 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4643 (direkt/dynamisch unklar); tests/test_server.py:5486 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 15252 | `providers/` | P2 | offen | tests/test_server.py:4355 (direkt/dynamisch unklar); tests/test_server.py:4387 (direkt/dynamisch unklar); tests/test_server.py:4421 (direkt/dynamisch unklar); tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 15256 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 15257 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 15260 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 15264 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 15277 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 15302 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 15326 | `activities/` | P3 | offen | tests/test_server.py:7713 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 15346 | `coach/context.py` | P7 | offen | tests/test_server.py:8616 (direkt/dynamisch unklar); tests/test_server.py:8627 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 15368 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 15377 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 15399 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8643 (direkt/dynamisch unklar); tests/test_server.py:8655 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 15423 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 15432 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8644 (direkt/dynamisch unklar); tests/test_server.py:8656 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 15461 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 15465 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5986 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 15482 | `coach/context.py` | P7 | offen | tests/test_server.py:6015 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 15486 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:6006 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 15498 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 15515 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 15542 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 15551 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 15568 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 15620 | `sync/` | P6 | offen | tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4623 (direkt/dynamisch unklar); tests/test_server.py:5872 (direkt/dynamisch unklar); tests/test_server.py:5900 (direkt/dynamisch unklar); tests/test_server.py:5921 (direkt/dynamisch unklar); tests/test_server.py:5948 (direkt/dynamisch unklar); tests/test_server.py:5975 (direkt/dynamisch unklar); tests/test_server.py:5999 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 15653 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5919 (direkt/dynamisch unklar); tests/test_server.py:8387 (direkt/dynamisch unklar); tests/test_server.py:8390 (direkt/dynamisch unklar); tests/test_server.py:8404 (direkt/dynamisch unklar); tests/test_server.py:8425 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8452 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8465 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 15667 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 15682 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5935 (direkt/dynamisch unklar); tests/test_server.py:8427 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8454 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 15691 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 15700 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 15712 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 15729 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:257 (direkt/dynamisch unklar); tests/test_server.py:8393 (direkt/dynamisch unklar); tests/test_server.py:8395 (direkt/dynamisch unklar); tests/test_server.py:8469 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 15737 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5943 (direkt/dynamisch unklar); tests/test_server.py:8399 (direkt/dynamisch unklar); tests/test_server.py:8410 (direkt/dynamisch unklar); tests/test_server.py:8426 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8474 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 15744 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 15745 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 15746 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 15746 | `coach/` | P7 | offen | tests/test_server.py:354 (direkt/dynamisch unklar); tests/test_server.py:410 (direkt/dynamisch unklar); tests/test_server.py:4880 (direkt/dynamisch unklar); tests/test_server.py:4883 (direkt/dynamisch unklar); tests/test_server.py:5233 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 15746 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 15746 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 15755 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 15763 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 15767 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 15772 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 15783 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 15808 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 15827 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 15839 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:3045 (direkt/dynamisch unklar); tests/test_server.py:3047 (direkt/dynamisch unklar); tests/test_server.py:5499 (direkt/dynamisch unklar); tests/test_server.py:5535 (direkt/dynamisch unklar); tests/test_server.py:5558 (direkt/dynamisch unklar); tests/test_server.py:5560 (direkt/dynamisch unklar); tests/test_server.py:5576 (direkt/dynamisch unklar); tests/test_server.py:5583 (direkt/dynamisch unklar); tests/test_server.py:5597 (direkt/dynamisch unklar); tests/test_server.py:5620 (direkt/dynamisch unklar); tests/test_server.py:5645 (direkt/dynamisch unklar); tests/test_server.py:5674 (direkt/dynamisch unklar); tests/test_server.py:5694 (direkt/dynamisch unklar); tests/test_server.py:5746 (direkt/dynamisch unklar); tests/test_server.py:5759 (direkt/dynamisch unklar); tests/test_server.py:5765 (direkt/dynamisch unklar); tests/test_server.py:5794 (direkt/dynamisch unklar); tests/test_server.py:5821 (direkt/dynamisch unklar); tests/test_server.py:5824 (direkt/dynamisch unklar); tests/test_server.py:5845 (direkt/dynamisch unklar); tests/test_server.py:691 (direkt/dynamisch unklar); tests/test_server.py:704 (direkt/dynamisch unklar); tests/test_server.py:780 (direkt/dynamisch unklar); tests/test_server.py:815 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 15862 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 15869 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 15876 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 15894 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 15904 | `coach/proposals.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:277 (direkt/dynamisch unklar); tests/test_server.py:302 (direkt/dynamisch unklar); tests/test_server.py:4549 (direkt/dynamisch unklar); tests/test_server.py:5480 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 15917 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 15926 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 15937 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 15969 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 15995 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 16015 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 16039 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 16051 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 16064 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 16078 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 16086 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 16097 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 16119 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 16129 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 16143 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 16155 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 16169 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 16177 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 16190 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 16199 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 16221 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 16239 | `planning/` | P4 | offen | tests/test_server.py:4910 (direkt/dynamisch unklar); tests/test_server.py:4932 (direkt/dynamisch unklar); tests/test_server.py:4951 (direkt/dynamisch unklar); tests/test_server.py:4973 (direkt/dynamisch unklar); tests/test_server.py:4988 (direkt/dynamisch unklar); tests/test_server.py:5004 (direkt/dynamisch unklar); tests/test_server.py:5022 (direkt/dynamisch unklar); tests/test_server.py:5044 (direkt/dynamisch unklar); tests/test_server.py:5062 (direkt/dynamisch unklar); tests/test_server.py:5085 (direkt/dynamisch unklar); tests/test_server.py:5129 (direkt/dynamisch unklar); tests/test_server.py:5154 (direkt/dynamisch unklar); tests/test_server.py:5175 (direkt/dynamisch unklar); tests/test_server.py:5190 (direkt/dynamisch unklar); tests/test_server.py:5209 (direkt/dynamisch unklar); tests/test_server.py:5226 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 16250 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 16260 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 16277 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 16288 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 16318 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 16336 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 16342 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 16355 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 16373 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 16389 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 16402 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 16416 | `planning/` | P4 | offen | tests/test_server.py:5600 (direkt/dynamisch unklar); tests/test_server.py:5647 (direkt/dynamisch unklar); tests/test_server.py:5675 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 16450 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:335 (direkt/dynamisch unklar); tests/test_server.py:366 (direkt/dynamisch unklar); tests/test_server.py:8749 (direkt/dynamisch unklar); tests/test_server.py:884 (direkt/dynamisch unklar); tests/test_server.py:962 (direkt/dynamisch unklar); tests/test_server.py:971 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 16463 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 16475 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 16490 | `planning/` | P4 | offen | tests/test_server.py:375 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 16502 | `planning/` | P4 | offen | tests/test_server.py:645 (direkt/dynamisch unklar); tests/test_server.py:655 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 16532 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 16540 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 16547 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 16569 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 16576 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 16582 | `coach/proposals.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 16600 | `planning/` | P4 | offen | tests/test_server.py:399 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 16628 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 16637 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 16664 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 16690 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 16695 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 16701 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 16715 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 16722 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 16730 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 16737 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 16746 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 16753 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 16766 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 16789 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 16803 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 16817 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 16845 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 16861 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 16880 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 16900 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 16922 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 16938 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 16955 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 16990 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 17002 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 17017 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 17037 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 17063 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 17081 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 17089 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 17110 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 17137 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 17161 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 17188 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 17209 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:289 (direkt/dynamisch unklar); tests/test_server.py:321 (direkt/dynamisch unklar); tests/test_server.py:345 (direkt/dynamisch unklar); tests/test_server.py:378 (direkt/dynamisch unklar); tests/test_server.py:400 (direkt/dynamisch unklar); tests/test_server.py:425 (direkt/dynamisch unklar); tests/test_server.py:432 (direkt/dynamisch unklar); tests/test_server.py:472 (direkt/dynamisch unklar); tests/test_server.py:501 (direkt/dynamisch unklar); tests/test_server.py:507 (direkt/dynamisch unklar); tests/test_server.py:5108 (direkt/dynamisch unklar); tests/test_server.py:511 (direkt/dynamisch unklar); tests/test_server.py:528 (direkt/dynamisch unklar); tests/test_server.py:532 (direkt/dynamisch unklar); tests/test_server.py:5505 (direkt/dynamisch unklar); tests/test_server.py:5541 (direkt/dynamisch unklar); tests/test_server.py:5626 (direkt/dynamisch unklar); tests/test_server.py:5700 (direkt/dynamisch unklar); tests/test_server.py:5724 (direkt/dynamisch unklar); tests/test_server.py:5729 (direkt/dynamisch unklar); tests/test_server.py:5778 (direkt/dynamisch unklar); tests/test_server.py:5800 (direkt/dynamisch unklar); tests/test_server.py:669 (direkt/dynamisch unklar); tests/test_server.py:711 (direkt/dynamisch unklar); tests/test_server.py:740 (direkt/dynamisch unklar); tests/test_server.py:759 (direkt/dynamisch unklar); tests/test_server.py:788 (direkt/dynamisch unklar); tests/test_server.py:821 (direkt/dynamisch unklar); tests/test_server.py:841 (direkt/dynamisch unklar); tests/test_server.py:868 (direkt/dynamisch unklar); tests/test_server.py:894 (direkt/dynamisch unklar); tests/test_server.py:913 (direkt/dynamisch unklar); tests/test_server.py:939 (direkt/dynamisch unklar); tests/test_server.py:964 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 17251 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 17255 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 17268 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8763 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 17280 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 17299 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 17315 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 17326 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 17348 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 17363 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 17381 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 17411 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 17417 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 17431 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 17441 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 17454 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 17467 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 17484 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 17497 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5838 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 17524 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 17541 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 17546 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 17555 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 17569 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 17582 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 17592 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 17605 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 17626 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 17649 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 17660 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 17669 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 17681 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 17695 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 17703 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 17718 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 17738 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 17762 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 17776 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 17787 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 17812 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 17828 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 17843 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 17900 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 17928 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 17958 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 17974 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 17994 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 18008 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 18020 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 18030 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 18081 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 18143 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 18147 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 18152 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 18170 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 18189 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 18199 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 18225 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 18263 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 18289 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 18314 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 18345 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 18385 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 18415 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 18435 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 18493 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 18497 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 18513 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 18529 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 18561 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 18605 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 18621 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 18640 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 18666 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 18743 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 18748 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 18757 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 18762 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 18789 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 18807 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 18836 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 18855 | `coach/service.py` | P7 | offen | tests/test_server.py:4451 (direkt/dynamisch unklar); tests/test_server.py:4466 (direkt/dynamisch unklar); tests/test_server.py:4480 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 18865 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 18880 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 18912 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 18927 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4553 (direkt/dynamisch unklar); tests/test_server.py:5491 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 18940 | `coach/authorization.py` | P7 | offen | tests/test_server.py:5879 (direkt/dynamisch unklar); tests/test_server.py:5882 (direkt/dynamisch unklar); tests/test_server.py:8403 (direkt/dynamisch unklar); tests/test_server.py:8406 (direkt/dynamisch unklar); tests/test_server.py:8407 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 18959 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 18972 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 18996 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 19012 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 19023 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 19038 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:247 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5908 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5932 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5964 (direkt/dynamisch unklar); tests/test_server.py:6027 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 19062 | `sync/` | P6 | offen | tests/test_server.py:4629 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 19103 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:254 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4628 (direkt/dynamisch unklar); tests/test_server.py:5906 (direkt/dynamisch unklar); tests/test_server.py:5925 (direkt/dynamisch unklar); tests/test_server.py:5952 (direkt/dynamisch unklar); tests/test_server.py:5981 (direkt/dynamisch unklar); tests/test_server.py:6005 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 19128 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 19154 | `coach/authorization.py` | P7 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 19164 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 19168 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 19176 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 19182 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 19192 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 19209 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 19240 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 19262 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 19277 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:148 (direkt/dynamisch unklar); tests/test_server.py:5909 (direkt/dynamisch unklar); tests/test_server.py:5933 (direkt/dynamisch unklar); tests/test_server.py:5987 (direkt/dynamisch unklar); tests/test_server.py:6030 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 19298 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 19313 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `local_now` | 19325 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1157 (direkt/dynamisch unklar); tests/test_server.py:1541 (direkt/dynamisch unklar); tests/test_server.py:1557 (direkt/dynamisch unklar); tests/test_server.py:1558 (direkt/dynamisch unklar); tests/test_server.py:1579 (direkt/dynamisch unklar); tests/test_server.py:1597 (direkt/dynamisch unklar); tests/test_server.py:1616 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1629 (direkt/dynamisch unklar); tests/test_server.py:1666 (direkt/dynamisch unklar); tests/test_server.py:1674 (direkt/dynamisch unklar); tests/test_server.py:1714 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2640 (direkt/dynamisch unklar); tests/test_server.py:2705 (direkt/dynamisch unklar); tests/test_server.py:2715 (direkt/dynamisch unklar); tests/test_server.py:2893 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2953 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2983 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2992 (direkt/dynamisch unklar); tests/test_server.py:3480 (direkt/dynamisch unklar); tests/test_server.py:3499 (direkt/dynamisch unklar); tests/test_server.py:3531 (direkt/dynamisch unklar); tests/test_server.py:3556 (direkt/dynamisch unklar); tests/test_server.py:3646 (direkt/dynamisch unklar); tests/test_server.py:3647 (direkt/dynamisch unklar); tests/test_server.py:3691 (direkt/dynamisch unklar); tests/test_server.py:496 (direkt/dynamisch unklar); tests/test_server.py:5248 (direkt/dynamisch unklar); tests/test_server.py:5297 (direkt/dynamisch unklar); tests/test_server.py:5314 (direkt/dynamisch unklar); tests/test_server.py:5336 (direkt/dynamisch unklar); tests/test_server.py:5363 (direkt/dynamisch unklar); tests/test_server.py:5395 (direkt/dynamisch unklar); tests/test_server.py:6070 (direkt/dynamisch unklar); tests/test_server.py:7404 (direkt/dynamisch unklar); tests/test_server.py:7722 (direkt/dynamisch unklar); tests/test_server.py:8504 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 19334 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1898 (direkt/dynamisch unklar); tests/test_server.py:1899 (direkt/dynamisch unklar); tests/test_server.py:1900 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 19342 | `sync/daily.py` | P6 | offen | tests/test_server.py:1897 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 19350 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 19355 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 19366 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 19378 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4160 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 19381 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 19388 | `coach/authorization.py` | P7 | offen | tests/test_server.py:4158 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 19405 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 19411 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 19419 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 19431 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 19463 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 19484 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 19498 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 19511 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 19530 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 19564 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1724 (direkt/dynamisch unklar); tests/test_server.py:1738 (direkt/dynamisch unklar); tests/test_server.py:1781 (direkt/dynamisch unklar); tests/test_server.py:1863 (direkt/dynamisch unklar); tests/test_server.py:8544 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 19638 | `http_api/` | P10 | offen | tests/test_server.py:1171 (direkt/dynamisch unklar); tests/test_server.py:2985 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 19674 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 19679 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 19683 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:97 (direkt/dynamisch unklar); tests/test_server.py:1221 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 19690 | `http_api/` | P10 | offen | tests/test_server.py:1193 (direkt/dynamisch unklar); tests/test_server.py:1201 (direkt/dynamisch unklar); tests/test_server.py:1624 (direkt/dynamisch unklar); tests/test_server.py:1669 (direkt/dynamisch unklar); tests/test_server.py:2334 (direkt/dynamisch unklar); tests/test_server.py:3696 (direkt/dynamisch unklar); tests/test_server.py:7333 (direkt/dynamisch unklar); tests/test_server.py:8544 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 19802 | `observability.py` | P1 | offen | tests/test_server.py:7867 (direkt/dynamisch unklar); tests/test_server.py:7919 (direkt/dynamisch unklar); tests/test_server.py:8033 (direkt/dynamisch unklar); tests/test_server.py:8064 (direkt/dynamisch unklar); tests/test_server.py:8315 (direkt/dynamisch unklar); tests/test_server.py:8351 (direkt/dynamisch unklar); tests/test_server.py:8600 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS_SECRET_KEYS` | 19819 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_VALUE_KEYS` | 19820 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_KEYS` | 19821 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_submitted_settings` | 19824 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_settings_file` | 19839 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_rewrite_settings_lines` | 19846 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `save_settings` | 19866 | `settings.py` | P1 | offen | tests/test_server.py:6660 (direkt/dynamisch unklar); tests/test_server.py:6676 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 19881 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 19897 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 19918 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 19932 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 19948 | `observability.py` | P1 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 19957 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7782 (direkt/dynamisch unklar); tests/test_server.py:7784 (direkt/dynamisch unklar); tests/test_server.py:7785 (direkt/dynamisch unklar); tests/test_server.py:7832 (direkt/dynamisch unklar); tests/test_server.py:7895 (direkt/dynamisch unklar); tests/test_server.py:7910 (direkt/dynamisch unklar); tests/test_server.py:8717 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 20020 | `backup/` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1404 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 20070 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 20071 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 20095 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 20099 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 20110 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 20114 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 20124 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 20132 | `backup/` | P9 | offen | tests/test_audit_remediation.py:171 (direkt/dynamisch unklar); tests/test_server.py:1419 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 20271 | `db/manager.py` | P1 | offen | tests/test_server.py:6599 (direkt/dynamisch unklar); tests/test_server.py:6612 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 20274 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 20287 | `backup/` | P9 | offen | tests/test_audit_remediation.py:275 (direkt/dynamisch unklar); tests/test_server.py:6588 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 20296 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 20317 | `coach/morning.py` | P8 | offen | tests/test_server.py:1447 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 20328 | `backup/` | P9 | offen | tests/test_audit_remediation.py:277 (direkt/dynamisch unklar); tests/test_server.py:6589 (direkt/dynamisch unklar); tests/test_server.py:6605 (direkt/dynamisch unklar); tests/test_server.py:6618 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 20333 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 20342 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 20359 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 20371 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 20389 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 20396 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 20417 | `coach/morning.py` | P8 | offen | tests/test_server.py:1487 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1503 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4642 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5485 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8663 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 20430 | `coach/morning.py` | P8 | offen | tests/test_server.py:1496 (direkt/dynamisch unklar); tests/test_server.py:1500 (direkt/dynamisch unklar); tests/test_server.py:1506 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 20445 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 20452 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 20459 | `privacy.py` | P9 | offen | tests/test_server.py:1499 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 20474 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:102 (direkt/dynamisch unklar); tests/test_provider_review.py:116 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (direkt/dynamisch unklar); tests/test_provider_review.py:146 (direkt/dynamisch unklar); tests/test_provider_review.py:164 (direkt/dynamisch unklar); tests/test_server.py:1488 (direkt/dynamisch unklar); tests/test_server.py:1504 (direkt/dynamisch unklar); tests/test_server.py:8664 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 20503 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 20504 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 20505 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 20506 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 20507 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 20508 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1319 (direkt/dynamisch unklar); tests/test_server.py:1327 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 20509 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1324 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 20510 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 20511 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 20512 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 20513 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7997 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 20516 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 20520 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:185 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:324 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7999 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 20545 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 20554 | `http_api/` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1283 (direkt/dynamisch unklar); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar); tests/test_server.py:1364 (direkt/dynamisch unklar); tests/test_server.py:1371 (direkt/dynamisch unklar); tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5898 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar); tests/test_server.py:5917 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 20558 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 20568 | `http_api/` | P10 | offen | tests/test_server.py:1325 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 20583 | `performance/` | P3 | offen | tests/test_server.py:7962 (direkt/dynamisch unklar); tests/test_server.py:7972 (direkt/dynamisch unklar); tests/test_server.py:7980 (direkt/dynamisch unklar); tests/test_server.py:7987 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 20625 | `http_api/` | P10 | offen | tests/test_server.py:1289 (direkt/dynamisch unklar); tests/test_server.py:1292 (direkt/dynamisch unklar); tests/test_server.py:1313 (direkt/dynamisch unklar); tests/test_server.py:1346 (direkt/dynamisch unklar); tests/test_server.py:1383 (direkt/dynamisch unklar); tests/test_server.py:3392 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 20651 | `observability.py` | P1 | offen | tests/test_provider_review.py:188 (direkt/dynamisch unklar); tests/test_provider_review.py:191 (direkt/dynamisch unklar); tests/test_provider_review.py:327 (direkt/dynamisch unklar); tests/test_server.py:3389 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 20670 | `observability.py` | P1 | offen | tests/test_server.py:1382 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 20678 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 20690 | `http_api/` | P10 | offen | tests/test_server.py:1364 (direkt/dynamisch unklar); tests/test_server.py:1371 (direkt/dynamisch unklar); tests/test_server.py:3394 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 20696 | `http_api/` | P10 | offen | tests/test_server.py:1264 (direkt/dynamisch unklar); tests/test_server.py:1270 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 20709 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:193 (direkt/dynamisch unklar); tests/test_server.py:1467 (direkt/dynamisch unklar); tests/test_server.py:1762 (direkt/dynamisch unklar); tests/test_server.py:7510 (direkt/dynamisch unklar); tests/test_server.py:7520 (direkt/dynamisch unklar); tests/test_server.py:7526 (direkt/dynamisch unklar); tests/test_server.py:7536 (direkt/dynamisch unklar); tests/test_server.py:7548 (direkt/dynamisch unklar); tests/test_server.py:7553 (direkt/dynamisch unklar); tests/test_server.py:7557 (direkt/dynamisch unklar); tests/test_server.py:7560 (direkt/dynamisch unklar); tests/test_server.py:7566 (direkt/dynamisch unklar); tests/test_server.py:7576 (direkt/dynamisch unklar); tests/test_server.py:7583 (direkt/dynamisch unklar); tests/test_server.py:7590 (direkt/dynamisch unklar); tests/test_server.py:7597 (direkt/dynamisch unklar); tests/test_server.py:8416 (direkt/dynamisch unklar); tests/test_server.py:8439 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 21388 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:193 (direkt/dynamisch unklar) |
| Funktion | `daily_sync_loop` | 21393 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 21406 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 21410 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 21416 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 21422 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 21428 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 21436 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:154 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 21443 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 21457 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 21462 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 21474 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 21486 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 21491 | `sync/` | P6 | offen | tests/test_server.py:978 (direkt/dynamisch unklar); tests/test_server.py:987 (direkt/dynamisch unklar) |
| Funktion | `main` | 21499 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar) |

## Zielverteilung

| Zielmodul | Einträge |
| --- | ---: |
| `activities/` | 48 |
| `athlete/` | 14 |
| `backend` | 1 |
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
| `backend/runtime` | 2 |
| `backend/settings` | 1 |
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
| `coach/authorization.py` | 77 |
| `coach/context.py` | 39 |
| `coach/conversation.py` | 8 |
| `coach/dialogue.py` | 18 |
| `coach/jobs.py` | 6 |
| `coach/morning.py` | 9 |
| `coach/proposals.py` | 43 |
| `coach/service.py` | 6 |
| `coach/streams.py` | 3 |
| `coach/tool_execution.py` | 8 |
| `config.py` | 8 |
| `db/` | 21 |
| `db/manager.py` | 6 |
| `db/schema.py` | 1 |
| `history/` | 34 |
| `http_api/` | 43 |
| `http_api/auth.py` | 14 |
| `http_api/pagination.py` | 9 |
| `observability.py` | 45 |
| `performance/` | 56 |
| `planning/` | 265 |
| `planning/competitions.py` | 70 |
| `privacy.py` | 4 |
| `providers/` | 88 |
| `providers/calendar.py` | 69 |
| `providers/http.py` | 16 |
| `providers/intervals_client.py` | 1 |
| `providers/workout_text.py` | 12 |
| `runtime/` | 3 |
| `server.py / Composition Root` | 56 |
| `settings.py` | 25 |
| `sync/` | 155 |
| `sync/competitions.py` | 3 |
| `sync/daily.py` | 1 |
| `sync/garmin.py` | 105 |
| `sync/scheduler.py` | 13 |
| `weather/` | 56 |

## Grenzen und offene Unsicherheiten

- AST-Aufrufauflösung erfasst nur direkte lokale Aufrufe; `getattr`, `globals()`, `sys.modules`, dekoratorbasierte Registrierung und Callback-Injektion benötigen eine manuelle Nachprüfung.
- Ein Name kann in mehreren Kategorien mit derselben Schreibweise vorkommen; Referenzzählungen sind deshalb namensbasiert und zeigen Ortsangaben, nicht vermeintliche Laufzeitidentität.
- Die Tabelle enthält bewusst auch Importbindungen, damit Rückimporte, spätere Re-Exports und der endgültige Composition-Root-Inhalt überprüfbar bleiben.
- Offene Zielzuordnungen müssen vor dem jeweiligen Umzug fachlich entschieden werden; sie gelten nicht als erledigt.
