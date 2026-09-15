# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `d22ea4eed15521e945bfc5d383072cd5ee20a5efd47bf6a5112a0822f4e74a46`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 21.835 physische Zeilen
- Inventareinträge: 1.715
- Definitionen (Funktionen/Klassen): 1.226
- Globale Bindungen einschließlich Imports: 289 Zuweisungen. 200 Imports
- Planbereich: bis Zeile 21.702; Einträge dahinter: 14 (zielbestimmt über Symbol-/Verantwortungsanalyse)
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
| P1 | 84 | 52 | 144 |
| P2 | 159 | 21 | 0 |
| P3 | 182 | 28 | 0 |
| P4 | 307 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 216 | 47 | 0 |
| P7 | 172 | 36 | 0 |
| P8 | 36 | 14 | 0 |
| P9 | 18 | 6 | 0 |
| P10 | 27 | 39 | 0 |
| P11 | 1 | 3 | 56 |

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
- `tests/test_provider_review.py:32: patch.object(server, "initialise_logging"),`
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
| `ProviderResyncGate` | 315 | – | `AppError`, `contextmanager`, `threading` | – | – |
| `provider_operation` | 366 | – | `GARMIN_RESYNC_GATE`, `INTERVALS_RESYNC_GATE` | – | – |
| `intervals_operation` | 371 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `garmin_operation` | 379 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `load_local_env` | 387 | – | `DATA_DIR`, `ROOT`, `load_config_env` | – | – |
| `IntervalsClient` | 395 | `_raise_chat_cancelled`, `compact_snapshot`, `deduplicate_api_records`, `intervals_workout_sport`, `latest_snapshot`, `local_now`, `selected`, `sync_date_windows`, `validate_intervals_workout_result`, `validate_workout_description`, `workout_event_payload` | `ALL_SYNC_DAYS`, `APP_NAME`, `Any`, `AppError`, `CONFIG`, `Callable`, `Config`, `IntervalsReadTransport`, `IntervalsWriteTransport`, `PLANNED_CALENDAR_FUTURE_DAYS`, `PLANNED_CALENDAR_HISTORY_DAYS`, `_raise_chat_cancelled`, … (+18) | – | – |
| `available_ai_providers` | 717 | – | `CONFIG` | – | – |
| `selected_ai_provider` | 726 | `available_ai_providers`, `get_kv` | `CONFIG`, `available_ai_providers`, `get_kv` | – | – |
| `save_ai_provider` | 740 | `available_ai_providers`, `available_model_options`, `selected_model`, `set_kv` | `Any`, `AppError`, `available_ai_providers`, `available_model_options`, `selected_model`, `set_kv` | – | – |
| `available_model_options` | 752 | `selected_ai_provider` | `CONFIG`, `GEMINI_MODEL_OPTIONS`, `MODEL_OPTIONS`, `selected_ai_provider` | – | – |
| `selected_model` | 761 | `available_model_options`, `get_kv`, `selected_ai_provider` | `CONFIG`, `available_model_options`, `get_kv`, `selected_ai_provider` | – | – |
| `save_model` | 769 | `available_model_options`, `selected_ai_provider`, `set_kv` | `Any`, `AppError`, `available_model_options`, `selected_ai_provider`, `set_kv` | – | – |
| `available_thinking_level_options` | 777 | – | `THINKING_LEVEL_OPTIONS` | – | – |
| `selected_thinking_level` | 781 | `get_kv` | `THINKING_LEVEL_OPTIONS`, `get_kv` | – | – |
| `save_thinking_level` | 787 | `set_kv` | `Any`, `AppError`, `THINKING_LEVEL_OPTIONS`, `set_kv` | – | – |
| `calendar_display_settings` | 795 | `get_kv` | `CALENDAR_DISPLAY_DEFAULTS`, `CALENDAR_DISPLAY_MAX_WEEKS`, `get_kv` | – | – |
| `save_calendar_display_settings` | 806 | `calendar_display_settings`, `set_kv` | `Any`, `AppError`, `CALENDAR_DISPLAY_MAX_WEEKS`, `calendar_display_settings`, `set_kv` | – | – |
| `_secret_variants` | 834 | – | `Any`, `quote`, `unquote` | – | – |
| `_safe_url_netloc` | 847 | – | `Any` | – | – |
| `_safe_provider_path` | 860 | – | `REDACTED_PATH`, `re`, `unquote` | – | – |
| `_unguessable_url_path_segment` | 883 | – | `re`, `unquote` | – | – |
| `_redact_url` | 893 | `_safe_url_netloc`, `_unguessable_url_path_segment` | `REDACTED_PATH`, `REDACTED_URL_QUERY_KEYS`, `_safe_url_netloc`, `_unguessable_url_path_segment`, `parse_qsl`, `re`, `urlencode`, `urlparse`, `urlunparse` | – | – |
| `_safe_calendar_url` | 917 | `_safe_url_netloc` | `CONFIG`, `_safe_url_netloc`, `urlparse`, `urlunparse` | – | – |
| `redact_text` | 927 | `_safe_calendar_url`, `_secret_variants` | `CONFIG`, `URL_VALUE_RE`, `_redact_url`, `_safe_calendar_url`, `_secret_variants`, `re` | – | – |
| `sanitize_log_value` | 953 | `redact_text`, `sanitize_log_value` | `Any`, `redact_text`, `sanitize_log_value` | – | – |
| `JsonLogFormatter` | 965 | `sanitize_log_value` | `Any`, `datetime`, `json`, `logging`, `sanitize_log_value`, `timezone` | – | – |
| `initialise_logging` | 981 | `JsonLogFormatter` | `DATA_DIR`, `JsonLogFormatter`, `LOGGER`, `LOG_PATH`, `RotatingFileHandler`, `logging`, `sys` | – | – |
| `external_result_context` | 1003 | – | `Any` | – | – |
| `external_call` | 1014 | `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `external_result_context`, `initialise_logging`, `operation_error_code` | `Any`, `AppError`, `LOGGER`, `OPERATION_CONTEXT`, `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `external_result_context`, `initialise_logging`, `operation_error_code`, `provider_error`, … (+1) | – | – |
| `serialise_conversation` | 1206 | – | `AppError`, `CHAT_LOCK_TIMEOUT_SECONDS`, `CHAT_QUEUE`, `OPENAI_CONVERSATION_LOCK`, `wraps` | – | – |
| `utc_now` | 1223 | – | `datetime`, `timezone` | – | – |
| `security_configuration_error` | 1238 | – | `CONFIG`, `SQLCIPHER_AVAILABLE` | – | – |
| `operation_trigger` | 1329 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 1335 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 1344 | – | `Any` | – | – |
| `log_operation_event` | 1354 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1381 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1402 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count`, `runtime_maintenance`, `wraps` | – | – |
| `database_manager` | 1445 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE` | – |
| `database` | 1472 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1478 | `database`, `get_kv`, `resume_interrupted_sync_jobs`, `set_kv`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `PROVIDER_RESYNC_KEYS`, `database`, `database_schema_is_current`, `database_table_names`, `datetime`, `get_kv`, `initialize_schema`, `json`, … (+5) | – | – |
| `_provider_refresh_cleanup` | 1520 | – | `Any`, `PROVIDER_REFRESH_MAX_ROWS`, `PROVIDER_REFRESH_RETENTION_DAYS`, `cleanup_refresh_history`, `datetime`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1525 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `runtime_events`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1537 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `runtime_events`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1571 | – | – | – | – |
| `_sync_job_error_class` | 1586 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1600 | – | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1609 | – | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1623 | `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1636 | `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1646 | `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1655 | – | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1665 | – | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1672 | `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1697 | `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1706 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1712 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1717 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1740 | – | `AppError` | – | – |
| `_pending_performance_job_id` | 1748 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1757 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1775 | `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1802 | – | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1811 | – | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1818 | – | `Any` | – | – |
| `_insert_sync_job` | 1828 | – | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 1853 | – | `Any`, `runtime_events` | – | – |
| `enqueue_sync_job` | 1867 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `runtime_maintenance`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 1894 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 1914 | `database`, `utc_now` | `Any`, `DB_LOCK`, `database`, `runtime_maintenance`, `utc_now` | – | – |
| `_sync_job_update` | 1935 | `database`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `runtime_events`, `utc_now` | – | – |
| `_sync_job_item_results` | 1973 | – | `Any` | – | – |
| `_sync_job_result_target` | 1979 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 1990 | `_sync_job_result_target`, `redact_text` | `Any`, `_sync_job_result_target`, `redact_text` | – | – |
| `_sync_job_completion_snapshot` | 2010 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 2025 | – | `runtime_events` | – | – |
| `_sync_job_update_from_result` | 2042 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 2055 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 2064 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 2071 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 2088 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 2100 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 2112 | `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 2135 | – | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 2144 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 2164 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 2184 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update`, `redact_text` | `Any`, `LOGGER`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update`, `redact_text` | – | – |
| `_run_claimed_sync_job` | 2202 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `runtime_maintenance` | – | – |
| `_sync_job_worker_loop` | 2212 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job`, `runtime_maintenance` | – | – |
| `start_sync_job_worker` | 2227 | `resume_interrupted_sync_jobs` | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `resume_interrupted_sync_jobs`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 2239 | `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_scheduled_provider_retry_at` | 2262 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_freshness_inputs` | 2281 | `_garmin_core_error_entries`, `get_kv`, `get_profile` | `Any`, `CONFIG`, `Path`, `WEATHER_CACHE_KEY`, `WEATHER_FAILURE_KEY`, `_garmin_core_error_entries`, `get_kv`, `get_profile`, `json` | – | – |
| `_provider_freshness_last_good_state` | 2315 | – | `Any`, `PROVIDER_REFRESH_STALE_SECONDS`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_fallback_error_code` | 2325 | – | – | – | – |
| `_provider_freshness_error_code` | 2329 | `_provider_fallback_error_code` | `Any`, `_provider_fallback_error_code` | – | – |
| `_provider_freshness_status` | 2337 | `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | `Any`, `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | – | – |
| `provider_freshness_state` | 2358 | `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | `Any`, `DB_LOCK`, `PROVIDER_REFRESH_LABELS`, `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | – | – |
| `_audit_projection_fields` | 2399 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 2413 | – | `Any`, `json` | – | – |
| `_audit_projection` | 2424 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 2448 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 2453 | – | `Any` | – | – |
| `_cleanup_change_history` | 2465 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 2475 | – | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 2492 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2531 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2563 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2574 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2586 | – | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2600 | – | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2616 | `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2654 | `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2674 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2684 | `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2709 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2730 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2740 | `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2749 | `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2775 | `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2791 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2820 | `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2835 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |
| `sync_period` | 2876 | `get_kv` | `ALL_SYNC_DAYS`, `SYNC_PERIOD_DEFAULTS`, `get_kv` | – | – |
| `set_sync_period` | 2887 | `set_kv` | `ALL_SYNC_DAYS`, `Any`, `AppError`, `set_kv` | – | – |
| `sync_date_windows` | 2899 | `local_now` | `ALL_SYNC_DAYS`, `SYNC_CHUNK_DAYS`, `SYNC_EARLIEST_DATE`, `date`, `local_now`, `split_date_windows` | – | – |
| `provider_sync_cursor` | 2910 | `database` | `Any`, `DB_LOCK`, `database`, `read_cursor` | – | – |
| `update_provider_sync_cursor` | 2915 | `database`, `utc_now` | `DB_LOCK`, `database`, `utc_now`, `write_cursor` | – | – |
| `set_kv` | 2921 | `database`, `set_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `set_kv`, `sqlite3` | – | – |
| `_safe_diagnostic_context` | 2929 | – | `Any` | – | – |
| `diagnostic_mapping_shape` | 2941 | `diagnostic_response_shape` | `Any`, `diagnostic_response_shape`, `re` | – | – |
| `diagnostic_sequence_shape` | 2953 | `diagnostic_response_shape` | `Any`, `diagnostic_response_shape` | – | – |
| `diagnostic_response_shape` | 2960 | `diagnostic_mapping_shape`, `diagnostic_sequence_shape` | `Any`, `diagnostic_mapping_shape`, `diagnostic_sequence_shape` | – | – |
| `diagnostic_capture_response` | 2977 | `diagnostic_response_shape` | `Any`, `diagnostic_response_shape` | – | – |
| `_safe_diagnostic_error` | 2982 | – | `Any`, `OPENAI_RESPONSE_ERROR_CODES`, `re` | – | – |

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
| Importbindung | `sys` | 26 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `threading` | 27 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_diagnostic_followups.py:170 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:37 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:56 (direkt/dynamisch unklar) |
| Importbindung | `tempfile` | 28 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7979 (direkt/dynamisch unklar) |
| Importbindung | `time` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/support.py:130 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:108 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:41 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:95 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:38 (direkt/dynamisch unklar); tests/test_coach_review.py:257 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:257 (direkt/dynamisch unklar); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:1325 (direkt/dynamisch unklar); tests/test_server.py:4236 (direkt/dynamisch unklar); tests/test_server.py:7998 (direkt/dynamisch unklar); tests/test_server.py:8195 (direkt/dynamisch unklar); tests/test_server.py:8378 (direkt/dynamisch unklar) |
| Importbindung | `uuid` | 30 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `zipfile` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ContextVar` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `nullcontext` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `contextmanager` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `dataclass` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `date` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1573 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `datetime` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `timedelta` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:496 (direkt/dynamisch unklar) |
| Importbindung | `timezone` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `wraps` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPResponse` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `BaseHTTPRequestHandler` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ThreadingHTTPServer` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `SimpleCookie` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `RotatingFileHandler` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Path` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Any` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Callable` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Iterator` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `NoReturn` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPError` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4659 (direkt/dynamisch unklar); tests/test_server.py:7842 (direkt/dynamisch unklar); tests/test_server.py:7873 (direkt/dynamisch unklar); tests/test_server.py:7924 (direkt/dynamisch unklar); tests/test_server.py:8109 (direkt/dynamisch unklar); tests/test_server.py:8153 (direkt/dynamisch unklar); tests/test_server.py:8168 (direkt/dynamisch unklar); tests/test_server.py:8261 (direkt/dynamisch unklar) |
| Importbindung | `URLError` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7914 (direkt/dynamisch unklar) |
| Importbindung | `parse_qs` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `parse_qsl` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `quote` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `unquote` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlencode` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlparse` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlunparse` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Request` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlopen` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4414 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4666 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4713 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4744 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4777 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4863 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7844 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7863 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7880 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7914 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7931 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8056 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8092 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8119 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8160 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8308 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8321 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8345 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8370 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `database_row_factory` | 47 | `backend/db` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ABORTED_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COMPETITION_NOT_FOUND_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_LIBRARY_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_PLANNING_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GEMINI_API_KEY_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERNAL_SERVER_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERVALS_API_KEY_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_LIBRARY_ID_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_DATE_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_ID_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `NOT_FOUND_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `OPENAI_API_KEY_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PLANNED_CALENDAR_RECHECK_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STALE_PLANNING_REVISION_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STRUCTURED_AUTHORIZATION_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `UNSUPPORTED_BYDAY_ERROR` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AppError` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:161 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1363 (direkt/dynamisch unklar); tests/test_server.py:1370 (direkt/dynamisch unklar); tests/test_server.py:1487 (direkt/dynamisch unklar); tests/test_server.py:1588 (direkt/dynamisch unklar); tests/test_server.py:1592 (direkt/dynamisch unklar); tests/test_server.py:1618 (direkt/dynamisch unklar); tests/test_server.py:1755 (direkt/dynamisch unklar); tests/test_server.py:2006 (direkt/dynamisch unklar); tests/test_server.py:2012 (direkt/dynamisch unklar); tests/test_server.py:2023 (direkt/dynamisch unklar); tests/test_server.py:2027 (direkt/dynamisch unklar); tests/test_server.py:2028 (direkt/dynamisch unklar); tests/test_server.py:2030 (direkt/dynamisch unklar); tests/test_server.py:2035 (direkt/dynamisch unklar); tests/test_server.py:2038 (direkt/dynamisch unklar); tests/test_server.py:2043 (direkt/dynamisch unklar); tests/test_server.py:2046 (direkt/dynamisch unklar); tests/test_server.py:2051 (direkt/dynamisch unklar); tests/test_server.py:2054 (direkt/dynamisch unklar); tests/test_server.py:2061 (direkt/dynamisch unklar); tests/test_server.py:2086 (direkt/dynamisch unklar); tests/test_server.py:223 (direkt/dynamisch unklar); tests/test_server.py:2342 (direkt/dynamisch unklar); tests/test_server.py:235 (direkt/dynamisch unklar); tests/test_server.py:2452 (direkt/dynamisch unklar); tests/test_server.py:2477 (direkt/dynamisch unklar); tests/test_server.py:2481 (direkt/dynamisch unklar); tests/test_server.py:2524 (direkt/dynamisch unklar); tests/test_server.py:2537 (direkt/dynamisch unklar); tests/test_server.py:2543 (direkt/dynamisch unklar); tests/test_server.py:2583 (direkt/dynamisch unklar); tests/test_server.py:2665 (direkt/dynamisch unklar); tests/test_server.py:2666 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2673 (direkt/dynamisch unklar); tests/test_server.py:288 (direkt/dynamisch unklar); tests/test_server.py:320 (direkt/dynamisch unklar); tests/test_server.py:3213 (direkt/dynamisch unklar); tests/test_server.py:3250 (direkt/dynamisch unklar); tests/test_server.py:3684 (direkt/dynamisch unklar); tests/test_server.py:3784 (direkt/dynamisch unklar); tests/test_server.py:3800 (direkt/dynamisch unklar); tests/test_server.py:3839 (direkt/dynamisch unklar); tests/test_server.py:3866 (direkt/dynamisch unklar); tests/test_server.py:3874 (direkt/dynamisch unklar); tests/test_server.py:3885 (direkt/dynamisch unklar); tests/test_server.py:3906 (direkt/dynamisch unklar); tests/test_server.py:3918 (direkt/dynamisch unklar); tests/test_server.py:3922 (direkt/dynamisch unklar); tests/test_server.py:399 (direkt/dynamisch unklar); tests/test_server.py:4110 (direkt/dynamisch unklar); tests/test_server.py:4271 (direkt/dynamisch unklar); tests/test_server.py:4332 (direkt/dynamisch unklar); tests/test_server.py:4429 (direkt/dynamisch unklar); tests/test_server.py:4442 (direkt/dynamisch unklar); tests/test_server.py:4452 (direkt/dynamisch unklar); tests/test_server.py:4467 (direkt/dynamisch unklar); tests/test_server.py:4481 (direkt/dynamisch unklar); tests/test_server.py:4564 (direkt/dynamisch unklar); tests/test_server.py:4654 (direkt/dynamisch unklar); tests/test_server.py:4656 (direkt/dynamisch unklar); tests/test_server.py:4667 (direkt/dynamisch unklar); tests/test_server.py:4710 (direkt/dynamisch unklar); tests/test_server.py:4778 (direkt/dynamisch unklar); tests/test_server.py:4827 (direkt/dynamisch unklar); tests/test_server.py:4871 (direkt/dynamisch unklar); tests/test_server.py:4873 (direkt/dynamisch unklar); tests/test_server.py:488 (direkt/dynamisch unklar); tests/test_server.py:4897 (direkt/dynamisch unklar); tests/test_server.py:4972 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5208 (direkt/dynamisch unklar); tests/test_server.py:5225 (direkt/dynamisch unklar); tests/test_server.py:5431 (direkt/dynamisch unklar); tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:5448 (direkt/dynamisch unklar); tests/test_server.py:5450 (direkt/dynamisch unklar); tests/test_server.py:5599 (direkt/dynamisch unklar); tests/test_server.py:5712 (direkt/dynamisch unklar); tests/test_server.py:5764 (direkt/dynamisch unklar); tests/test_server.py:5777 (direkt/dynamisch unklar); tests/test_server.py:5985 (direkt/dynamisch unklar); tests/test_server.py:6091 (direkt/dynamisch unklar); tests/test_server.py:6095 (direkt/dynamisch unklar); tests/test_server.py:6104 (direkt/dynamisch unklar); tests/test_server.py:6108 (direkt/dynamisch unklar); tests/test_server.py:6126 (direkt/dynamisch unklar); tests/test_server.py:6137 (direkt/dynamisch unklar); tests/test_server.py:6604 (direkt/dynamisch unklar); tests/test_server.py:6617 (direkt/dynamisch unklar); tests/test_server.py:6629 (direkt/dynamisch unklar); tests/test_server.py:739 (direkt/dynamisch unklar); tests/test_server.py:7552 (direkt/dynamisch unklar); tests/test_server.py:7559 (direkt/dynamisch unklar); tests/test_server.py:758 (direkt/dynamisch unklar); tests/test_server.py:7817 (direkt/dynamisch unklar); tests/test_server.py:7825 (direkt/dynamisch unklar); tests/test_server.py:7845 (direkt/dynamisch unklar); tests/test_server.py:7881 (direkt/dynamisch unklar); tests/test_server.py:7915 (direkt/dynamisch unklar); tests/test_server.py:7932 (direkt/dynamisch unklar); tests/test_server.py:8120 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8175 (direkt/dynamisch unklar); tests/test_server.py:8186 (direkt/dynamisch unklar); tests/test_server.py:8267 (direkt/dynamisch unklar); tests/test_server.py:8322 (direkt/dynamisch unklar); tests/test_server.py:8346 (direkt/dynamisch unklar); tests/test_server.py:8376 (direkt/dynamisch unklar); tests/test_server.py:8389 (direkt/dynamisch unklar); tests/test_server.py:8392 (direkt/dynamisch unklar); tests/test_server.py:8484 (direkt/dynamisch unklar); tests/test_server.py:8493 (direkt/dynamisch unklar); tests/test_server.py:8496 (direkt/dynamisch unklar); tests/test_server.py:8499 (direkt/dynamisch unklar); tests/test_server.py:8577 (direkt/dynamisch unklar); tests/test_server.py:8626 (direkt/dynamisch unklar); tests/test_server.py:8647 (direkt/dynamisch unklar); tests/test_server.py:8747 (direkt/dynamisch unklar); tests/test_server.py:963 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Importbindung | `ClientDisconnected` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8371 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8420 (direkt/dynamisch unklar) |
| Importbindung | `provider_error` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `public_app_error_status` | 48 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4655 (direkt/dynamisch unklar); tests/test_server.py:4656 (direkt/dynamisch unklar) |
| Importbindung | `runtime_events` | 70 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `runtime_maintenance` | 71 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
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
| Globale Bindung | `DATA_DIR` | 173 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_server.py:103 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:118 (direkt/dynamisch unklar); tests/test_server.py:174 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2846 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3387 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6580 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6655 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6675 (Monkeypatch/getattr/sys.modules); tests/test_server.py:94 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 174 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:104 (direkt/dynamisch unklar); tests/test_server.py:108 (direkt/dynamisch unklar); tests/test_server.py:110 (direkt/dynamisch unklar); tests/test_server.py:119 (direkt/dynamisch unklar); tests/test_server.py:2846 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3387 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6580 (Monkeypatch/getattr/sys.modules); tests/test_server.py:95 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 175 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:30 (Monkeypatch/getattr/sys.modules); tests/test_server.py:105 (direkt/dynamisch unklar); tests/test_server.py:111 (direkt/dynamisch unklar); tests/test_server.py:120 (direkt/dynamisch unklar); tests/test_server.py:96 (direkt/dynamisch unklar) |
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
| Globale Bindung | `REDACTED_PATH` | 226 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UUID_PATTERN` | 227 | `http_api/` | P10 | offen | tests/test_server.py:3212 (direkt/dynamisch unklar) |
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
| Globale Bindung | `APP_VERSION` | 242 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:7335 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 243 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 244 | `http_api/` | P10 | offen | tests/test_server.py:4874 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 245 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 246 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 247 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 248 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 249 | `coach/streams.py` | P8 | offen | tests/test_server.py:1466 (direkt/dynamisch unklar); tests/test_server.py:1476 (direkt/dynamisch unklar); tests/test_server.py:1477 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_EXTERNAL_CALENDAR_BYTES` | 250 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_FETCH_TIMEOUT_SECONDS` | 251 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_CONNECTION_TIMEOUT_SECONDS` | 252 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_EXTERNAL_RESPONSE_BYTES` | 253 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_DEFAULT_MAX_OUTPUT_TOKENS` | 257 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LONG_PLAN_MAX_OUTPUT_TOKENS` | 258 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_FOLLOWUP_MAX_OUTPUT_TOKENS` | 259 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_TIMEOUT_SECONDS` | 260 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MESSAGE_ATTACHMENTS_QUERY` | 261 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_ERROR_CODES` | 263 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_BASE_URL` | 271 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 272 | `providers/` | P2 | offen | tests/test_server.py:5860 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 273 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 274 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 275 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 276 | `coach/` | P7 | offen | tests/test_server.py:4902 (direkt/dynamisch unklar); tests/test_server.py:5228 (direkt/dynamisch unklar); tests/test_server.py:5236 (direkt/dynamisch unklar); tests/test_server.py:5588 (direkt/dynamisch unklar); tests/test_server.py:5718 (direkt/dynamisch unklar); tests/test_server.py:5728 (direkt/dynamisch unklar); tests/test_server.py:5730 (direkt/dynamisch unklar); tests/test_server.py:5733 (direkt/dynamisch unklar); tests/test_server.py:5736 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5750 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 277 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 278 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:183 (direkt/dynamisch unklar); tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1011 (direkt/dynamisch unklar); tests/test_server.py:125 (direkt/dynamisch unklar); tests/test_server.py:1285 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1293 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1314 (direkt/dynamisch unklar); tests/test_server.py:1318 (direkt/dynamisch unklar); tests/test_server.py:1395 (direkt/dynamisch unklar); tests/test_server.py:1507 (direkt/dynamisch unklar); tests/test_server.py:156 (direkt/dynamisch unklar); tests/test_server.py:1644 (direkt/dynamisch unklar); tests/test_server.py:2529 (direkt/dynamisch unklar); tests/test_server.py:2590 (direkt/dynamisch unklar); tests/test_server.py:2603 (direkt/dynamisch unklar); tests/test_server.py:2659 (direkt/dynamisch unklar); tests/test_server.py:2682 (direkt/dynamisch unklar); tests/test_server.py:2811 (direkt/dynamisch unklar); tests/test_server.py:2824 (direkt/dynamisch unklar); tests/test_server.py:2829 (direkt/dynamisch unklar); tests/test_server.py:3027 (direkt/dynamisch unklar); tests/test_server.py:3107 (direkt/dynamisch unklar); tests/test_server.py:4630 (direkt/dynamisch unklar); tests/test_server.py:4921 (direkt/dynamisch unklar); tests/test_server.py:5053 (direkt/dynamisch unklar); tests/test_server.py:5076 (direkt/dynamisch unklar); tests/test_server.py:5099 (direkt/dynamisch unklar); tests/test_server.py:5121 (direkt/dynamisch unklar); tests/test_server.py:5135 (direkt/dynamisch unklar); tests/test_server.py:5141 (direkt/dynamisch unklar); tests/test_server.py:5158 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5488 (direkt/dynamisch unklar); tests/test_server.py:5530 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5641 (direkt/dynamisch unklar); tests/test_server.py:5883 (direkt/dynamisch unklar); tests/test_server.py:5895 (direkt/dynamisch unklar); tests/test_server.py:5914 (direkt/dynamisch unklar); tests/test_server.py:595 (direkt/dynamisch unklar); tests/test_server.py:5988 (direkt/dynamisch unklar); tests/test_server.py:6010 (direkt/dynamisch unklar); tests/test_server.py:6019 (direkt/dynamisch unklar); tests/test_server.py:6144 (direkt/dynamisch unklar); tests/test_server.py:639 (direkt/dynamisch unklar); tests/test_server.py:6436 (direkt/dynamisch unklar); tests/test_server.py:6499 (direkt/dynamisch unklar); tests/test_server.py:650 (direkt/dynamisch unklar); tests/test_server.py:6544 (direkt/dynamisch unklar); tests/test_server.py:6583 (direkt/dynamisch unklar); tests/test_server.py:6592 (direkt/dynamisch unklar); tests/test_server.py:664 (direkt/dynamisch unklar); tests/test_server.py:6768 (direkt/dynamisch unklar); tests/test_server.py:6777 (direkt/dynamisch unklar); tests/test_server.py:6787 (direkt/dynamisch unklar); tests/test_server.py:6938 (direkt/dynamisch unklar); tests/test_server.py:7732 (direkt/dynamisch unklar); tests/test_server.py:8559 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8564 (direkt/dynamisch unklar); tests/test_server.py:8700 (direkt/dynamisch unklar); tests/test_server.py:8714 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 279 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7742 (direkt/dynamisch unklar); tests/test_server.py:7754 (direkt/dynamisch unklar); tests/test_server.py:7757 (direkt/dynamisch unklar); tests/test_server.py:7770 (direkt/dynamisch unklar); tests/test_server.py:7771 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 280 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 281 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 282 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 283 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 284 | `performance/` | P3 | offen | tests/test_server.py:603 (direkt/dynamisch unklar); tests/test_server.py:609 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 285 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_LOCK` | 286 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 287 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:150 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 288 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:151 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 289 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8477 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 290 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8477 (direkt/dynamisch unklar); tests/test_server.py:8490 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 291 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 292 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 293 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 294 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 295 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 296 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:255 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 297 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:284 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 298 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 299 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 300 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 301 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 302 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 303 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 304 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 305 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5895 (direkt/dynamisch unklar); tests/test_server.py:5914 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 306 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LOCK` | 307 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7994 (direkt/dynamisch unklar); tests/test_server.py:8000 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 308 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7995 (direkt/dynamisch unklar); tests/test_server.py:7996 (direkt/dynamisch unklar); tests/test_server.py:8001 (direkt/dynamisch unklar); tests/test_server.py:8002 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 309 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 310 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 311 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 312 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Klasse | `ProviderResyncGate` | 315 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 362 | `sync/` | P6 | offen | tests/test_server.py:6622 (direkt/dynamisch unklar); tests/test_server.py:6637 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 363 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 366 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 371 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 379 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `load_local_env` | 387 | `config.py` | P1 | offen | tests/test_server.py:6667 (direkt/dynamisch unklar); tests/test_server.py:6692 (direkt/dynamisch unklar) |
| Globale Bindung | `CONFIG` | 392 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:153 (direkt/dynamisch unklar); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (direkt/dynamisch unklar); tests/test_provider_review.py:196 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:314 (direkt/dynamisch unklar); tests/test_provider_review.py:322 (direkt/dynamisch unklar); tests/test_provider_review.py:323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:100 (direkt/dynamisch unklar); tests/test_server.py:117 (direkt/dynamisch unklar); tests/test_server.py:1198 (direkt/dynamisch unklar); tests/test_server.py:1269 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1269 (direkt/dynamisch unklar); tests/test_server.py:172 (direkt/dynamisch unklar); tests/test_server.py:174 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2534 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2534 (direkt/dynamisch unklar); tests/test_server.py:2620 (direkt/dynamisch unklar); tests/test_server.py:2621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2649 (direkt/dynamisch unklar); tests/test_server.py:2650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2664 (direkt/dynamisch unklar); tests/test_server.py:2665 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2732 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2732 (direkt/dynamisch unklar); tests/test_server.py:2827 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2827 (direkt/dynamisch unklar); tests/test_server.py:2836 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2836 (direkt/dynamisch unklar); tests/test_server.py:2845 (direkt/dynamisch unklar); tests/test_server.py:2846 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3386 (direkt/dynamisch unklar); tests/test_server.py:3387 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3628 (direkt/dynamisch unklar); tests/test_server.py:3701 (direkt/dynamisch unklar); tests/test_server.py:3721 (direkt/dynamisch unklar); tests/test_server.py:3732 (direkt/dynamisch unklar); tests/test_server.py:3751 (direkt/dynamisch unklar); tests/test_server.py:3927 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3927 (direkt/dynamisch unklar); tests/test_server.py:3945 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3945 (direkt/dynamisch unklar); tests/test_server.py:3955 (direkt/dynamisch unklar); tests/test_server.py:4200 (direkt/dynamisch unklar); tests/test_server.py:4201 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4268 (direkt/dynamisch unklar); tests/test_server.py:4276 (direkt/dynamisch unklar); tests/test_server.py:4368 (direkt/dynamisch unklar); tests/test_server.py:4370 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4413 (direkt/dynamisch unklar); tests/test_server.py:4414 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4438 (direkt/dynamisch unklar); tests/test_server.py:4439 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4562 (direkt/dynamisch unklar); tests/test_server.py:4563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4577 (direkt/dynamisch unklar); tests/test_server.py:4578 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4588 (direkt/dynamisch unklar); tests/test_server.py:4589 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4603 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4603 (direkt/dynamisch unklar); tests/test_server.py:4607 (direkt/dynamisch unklar); tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4617 (direkt/dynamisch unklar); tests/test_server.py:4622 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4641 (direkt/dynamisch unklar); tests/test_server.py:4642 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4796 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4796 (direkt/dynamisch unklar); tests/test_server.py:4814 (direkt/dynamisch unklar); tests/test_server.py:4815 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4818 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4818 (direkt/dynamisch unklar); tests/test_server.py:4826 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4826 (direkt/dynamisch unklar); tests/test_server.py:4838 (direkt/dynamisch unklar); tests/test_server.py:4839 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4862 (direkt/dynamisch unklar); tests/test_server.py:4863 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4869 (direkt/dynamisch unklar); tests/test_server.py:4870 (Monkeypatch/getattr/sys.modules); tests/test_server.py:56 (direkt/dynamisch unklar); tests/test_server.py:57 (direkt/dynamisch unklar); tests/test_server.py:585 (direkt/dynamisch unklar); tests/test_server.py:586 (Monkeypatch/getattr/sys.modules); tests/test_server.py:602 (direkt/dynamisch unklar); tests/test_server.py:605 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6061 (direkt/dynamisch unklar); tests/test_server.py:6063 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6075 (direkt/dynamisch unklar); tests/test_server.py:6076 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6090 (direkt/dynamisch unklar); tests/test_server.py:6092 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6102 (direkt/dynamisch unklar); tests/test_server.py:6105 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6115 (direkt/dynamisch unklar); tests/test_server.py:6123 (Monkeypatch/getattr/sys.modules); tests/test_server.py:613 (direkt/dynamisch unklar); tests/test_server.py:6135 (direkt/dynamisch unklar); tests/test_server.py:6136 (Monkeypatch/getattr/sys.modules); tests/test_server.py:614 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6163 (direkt/dynamisch unklar); tests/test_server.py:6164 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6203 (direkt/dynamisch unklar); tests/test_server.py:6204 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6225 (direkt/dynamisch unklar); tests/test_server.py:6226 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6247 (direkt/dynamisch unklar); tests/test_server.py:6248 (Monkeypatch/getattr/sys.modules); tests/test_server.py:626 (direkt/dynamisch unklar); tests/test_server.py:6266 (direkt/dynamisch unklar); tests/test_server.py:6267 (Monkeypatch/getattr/sys.modules); tests/test_server.py:627 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6286 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6286 (direkt/dynamisch unklar); tests/test_server.py:6340 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6340 (direkt/dynamisch unklar); tests/test_server.py:6349 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6349 (direkt/dynamisch unklar); tests/test_server.py:6368 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6368 (direkt/dynamisch unklar); tests/test_server.py:6377 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6377 (direkt/dynamisch unklar); tests/test_server.py:6386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6386 (direkt/dynamisch unklar); tests/test_server.py:6394 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6394 (direkt/dynamisch unklar); tests/test_server.py:6411 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6411 (direkt/dynamisch unklar); tests/test_server.py:6455 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6455 (direkt/dynamisch unklar); tests/test_server.py:6487 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6487 (direkt/dynamisch unklar); tests/test_server.py:6533 (direkt/dynamisch unklar); tests/test_server.py:6558 (direkt/dynamisch unklar); tests/test_server.py:6566 (direkt/dynamisch unklar); tests/test_server.py:6567 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6578 (direkt/dynamisch unklar); tests/test_server.py:6580 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6625 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6625 (direkt/dynamisch unklar); tests/test_server.py:6645 (direkt/dynamisch unklar); tests/test_server.py:6646 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6823 (direkt/dynamisch unklar); tests/test_server.py:6855 (direkt/dynamisch unklar); tests/test_server.py:6893 (direkt/dynamisch unklar); tests/test_server.py:6925 (direkt/dynamisch unklar); tests/test_server.py:6941 (direkt/dynamisch unklar); tests/test_server.py:6980 (direkt/dynamisch unklar); tests/test_server.py:7013 (direkt/dynamisch unklar); tests/test_server.py:7040 (direkt/dynamisch unklar); tests/test_server.py:7323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7323 (direkt/dynamisch unklar); tests/test_server.py:7790 (direkt/dynamisch unklar); tests/test_server.py:7794 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7815 (direkt/dynamisch unklar); tests/test_server.py:7816 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7840 (direkt/dynamisch unklar); tests/test_server.py:7844 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7944 (direkt/dynamisch unklar); tests/test_server.py:7945 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7954 (direkt/dynamisch unklar); tests/test_server.py:7955 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8025 (direkt/dynamisch unklar); tests/test_server.py:8027 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8265 (direkt/dynamisch unklar); tests/test_server.py:8266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8505 (direkt/dynamisch unklar); tests/test_server.py:8506 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8575 (direkt/dynamisch unklar); tests/test_server.py:8576 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8670 (direkt/dynamisch unklar); tests/test_server.py:8677 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8688 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8744 (direkt/dynamisch unklar); tests/test_server.py:8745 (Monkeypatch/getattr/sys.modules); tests/test_server.py:93 (direkt/dynamisch unklar); tests/test_server.py:974 (direkt/dynamisch unklar); tests/test_server.py:975 (Monkeypatch/getattr/sys.modules); tests/test_server.py:983 (direkt/dynamisch unklar); tests/test_server.py:984 (Monkeypatch/getattr/sys.modules) |
| Klasse | `IntervalsClient` | 395 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:43 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:54 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:70 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:81 (direkt/dynamisch unklar); tests/test_server.py:3628 (direkt/dynamisch unklar); tests/test_server.py:3701 (direkt/dynamisch unklar); tests/test_server.py:3721 (direkt/dynamisch unklar); tests/test_server.py:3732 (direkt/dynamisch unklar); tests/test_server.py:3751 (direkt/dynamisch unklar); tests/test_server.py:3823 (direkt/dynamisch unklar); tests/test_server.py:3851 (direkt/dynamisch unklar); tests/test_server.py:3882 (direkt/dynamisch unklar); tests/test_server.py:3883 (direkt/dynamisch unklar); tests/test_server.py:3884 (direkt/dynamisch unklar); tests/test_server.py:3902 (direkt/dynamisch unklar); tests/test_server.py:3946 (direkt/dynamisch unklar); tests/test_server.py:3947 (direkt/dynamisch unklar); tests/test_server.py:3955 (direkt/dynamisch unklar); tests/test_server.py:4268 (direkt/dynamisch unklar); tests/test_server.py:4276 (direkt/dynamisch unklar); tests/test_server.py:6064 (direkt/dynamisch unklar); tests/test_server.py:6077 (direkt/dynamisch unklar); tests/test_server.py:6093 (direkt/dynamisch unklar); tests/test_server.py:6106 (direkt/dynamisch unklar); tests/test_server.py:6124 (direkt/dynamisch unklar); tests/test_server.py:615 (direkt/dynamisch unklar); tests/test_server.py:6165 (direkt/dynamisch unklar); tests/test_server.py:6166 (direkt/dynamisch unklar); tests/test_server.py:6205 (direkt/dynamisch unklar); tests/test_server.py:6227 (direkt/dynamisch unklar); tests/test_server.py:6249 (direkt/dynamisch unklar); tests/test_server.py:6250 (direkt/dynamisch unklar); tests/test_server.py:6268 (direkt/dynamisch unklar); tests/test_server.py:628 (direkt/dynamisch unklar); tests/test_server.py:6469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6532 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6557 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6822 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6854 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6892 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6924 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6940 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6979 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7012 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7039 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7712 (direkt/dynamisch unklar); tests/test_server.py:8028 (direkt/dynamisch unklar); tests/test_server.py:8029 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 698 | `observability.py` | P1 | offen | tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:23 (direkt/dynamisch unklar); tests/test_provider_review.py:31 (direkt/dynamisch unklar); tests/test_provider_review.py:40 (direkt/dynamisch unklar); tests/test_provider_review.py:42 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_server.py:7535 (direkt/dynamisch unklar); tests/test_server.py:7779 (direkt/dynamisch unklar); tests/test_server.py:7780 (direkt/dynamisch unklar); tests/test_server.py:7865 (direkt/dynamisch unklar); tests/test_server.py:7917 (direkt/dynamisch unklar); tests/test_server.py:8031 (direkt/dynamisch unklar); tests/test_server.py:8062 (direkt/dynamisch unklar); tests/test_server.py:8598 (direkt/dynamisch unklar) |
| Globale Bindung | `MODEL_OPTIONS` | 699 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_MODEL_OPTIONS` | 704 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `THINKING_LEVEL_OPTIONS` | 708 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_DISPLAY_DEFAULTS` | 713 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_DISPLAY_MAX_WEEKS` | 714 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `available_ai_providers` | 717 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_ai_provider` | 726 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:382 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4590 (direkt/dynamisch unklar) |
| Funktion | `save_ai_provider` | 740 | `settings.py` | P1 | offen | tests/test_server.py:4592 (direkt/dynamisch unklar); tests/test_server.py:4598 (direkt/dynamisch unklar) |
| Funktion | `available_model_options` | 752 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_model` | 761 | `settings.py` | P1 | offen | tests/test_server.py:4596 (direkt/dynamisch unklar); tests/test_server.py:4599 (direkt/dynamisch unklar); tests/test_server.py:5428 (direkt/dynamisch unklar); tests/test_server.py:5430 (direkt/dynamisch unklar) |
| Funktion | `save_model` | 769 | `settings.py` | P1 | offen | tests/test_server.py:4591 (direkt/dynamisch unklar); tests/test_server.py:4597 (direkt/dynamisch unklar); tests/test_server.py:5429 (direkt/dynamisch unklar); tests/test_server.py:5432 (direkt/dynamisch unklar) |
| Funktion | `available_thinking_level_options` | 777 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_thinking_level` | 781 | `settings.py` | P1 | offen | tests/test_server.py:5435 (direkt/dynamisch unklar); tests/test_server.py:5437 (direkt/dynamisch unklar) |
| Funktion | `save_thinking_level` | 787 | `settings.py` | P1 | offen | tests/test_server.py:5436 (direkt/dynamisch unklar); tests/test_server.py:5439 (direkt/dynamisch unklar); tests/test_server.py:5456 (direkt/dynamisch unklar) |
| Funktion | `calendar_display_settings` | 795 | `settings.py` | P1 | offen | tests/test_server.py:5442 (direkt/dynamisch unklar); tests/test_server.py:5447 (direkt/dynamisch unklar); tests/test_server.py:5453 (direkt/dynamisch unklar) |
| Funktion | `save_calendar_display_settings` | 806 | `settings.py` | P1 | offen | tests/test_server.py:5444 (direkt/dynamisch unklar); tests/test_server.py:5449 (direkt/dynamisch unklar); tests/test_server.py:5451 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTED_URL_QUERY_KEYS` | 827 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `URL_VALUE_RE` | 831 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_secret_variants` | 834 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_url_netloc` | 847 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_provider_path` | 860 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_unguessable_url_path_segment` | 883 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_redact_url` | 893 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_calendar_url` | 917 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `redact_text` | 927 | `observability.py` | P1 | offen | tests/test_server.py:4604 (direkt/dynamisch unklar); tests/test_server.py:7805 (direkt/dynamisch unklar) |
| Funktion | `sanitize_log_value` | 953 | `observability.py` | P1 | offen | keine statisch gefunden |
| Klasse | `JsonLogFormatter` | 965 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `initialise_logging` | 981 | `observability.py` | P1 | offen | tests/test_provider_review.py:32 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7843 (direkt/dynamisch unklar); tests/test_server.py:7913 (direkt/dynamisch unklar); tests/test_server.py:8026 (direkt/dynamisch unklar); tests/test_server.py:8055 (direkt/dynamisch unklar); tests/test_server.py:8329 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar) |
| Funktion | `external_result_context` | 1003 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `external_call` | 1014 | `providers/http.py` | P2 | offen | tests/test_server.py:1737 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7818 (direkt/dynamisch unklar); tests/test_server.py:7894 (direkt/dynamisch unklar); tests/test_server.py:7909 (direkt/dynamisch unklar); tests/test_server.py:8592 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 1077 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 1096 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 1097 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 1098 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 1099 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 1100 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 1101 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 1102 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 1103 | `weather/` | P3 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_server.py:1186 (direkt/dynamisch unklar); tests/test_server.py:1188 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1215 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1530 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 1104 | `weather/` | P3 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 1105 | `history/` | P5 | offen | tests/test_server.py:4210 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 1106 | `weather/` | P3 | offen | tests/test_server.py:1206 (direkt/dynamisch unklar); tests/test_server.py:1208 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 1107 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 1108 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 1109 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 1110 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 1111 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 1141 | `weather/` | P3 | offen | tests/test_server.py:7468 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 1173 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `serialise_conversation` | 1206 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8480 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 1223 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:170 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:80 (direkt/dynamisch unklar); tests/test_audit_remediation.py:94 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1010 (direkt/dynamisch unklar); tests/test_server.py:1161 (direkt/dynamisch unklar); tests/test_server.py:1164 (direkt/dynamisch unklar); tests/test_server.py:1232 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1398 (direkt/dynamisch unklar); tests/test_server.py:1402 (direkt/dynamisch unklar); tests/test_server.py:1518 (direkt/dynamisch unklar); tests/test_server.py:1647 (direkt/dynamisch unklar); tests/test_server.py:2532 (direkt/dynamisch unklar); tests/test_server.py:2593 (direkt/dynamisch unklar); tests/test_server.py:2606 (direkt/dynamisch unklar); tests/test_server.py:2662 (direkt/dynamisch unklar); tests/test_server.py:2685 (direkt/dynamisch unklar); tests/test_server.py:2814 (direkt/dynamisch unklar); tests/test_server.py:3110 (direkt/dynamisch unklar); tests/test_server.py:3114 (direkt/dynamisch unklar); tests/test_server.py:5055 (direkt/dynamisch unklar); tests/test_server.py:5078 (direkt/dynamisch unklar); tests/test_server.py:5101 (direkt/dynamisch unklar); tests/test_server.py:5123 (direkt/dynamisch unklar); tests/test_server.py:5144 (direkt/dynamisch unklar); tests/test_server.py:5168 (direkt/dynamisch unklar); tests/test_server.py:5619 (direkt/dynamisch unklar); tests/test_server.py:5643 (direkt/dynamisch unklar); tests/test_server.py:5898 (direkt/dynamisch unklar); tests/test_server.py:5917 (direkt/dynamisch unklar); tests/test_server.py:7733 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 1227 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 1228 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 1229 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 1230 | `planning/` | P4 | offen | tests/test_server.py:5054 (direkt/dynamisch unklar); tests/test_server.py:5077 (direkt/dynamisch unklar); tests/test_server.py:5100 (direkt/dynamisch unklar); tests/test_server.py:5122 (direkt/dynamisch unklar); tests/test_server.py:5136 (direkt/dynamisch unklar); tests/test_server.py:5143 (direkt/dynamisch unklar); tests/test_server.py:5159 (direkt/dynamisch unklar); tests/test_server.py:5167 (direkt/dynamisch unklar); tests/test_server.py:5619 (direkt/dynamisch unklar); tests/test_server.py:5642 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 1231 | `planning/` | P4 | offen | tests/test_server.py:7733 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 1232 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4552 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 1233 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 1234 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 1235 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `security_configuration_error` | 1238 | `config.py` | P1 | offen | tests/test_audit_remediation.py:190 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:184 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:316 (direkt/dynamisch unklar) |
| Globale Bindung | `OPERATION_CONTEXT` | 1248 | `observability.py` | P1 | offen | tests/test_server.py:8012 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 1249 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:181 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 1250 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_provider_review.py:49 (direkt/dynamisch unklar); tests/test_server.py:182 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETENTION_DAYS` | 1252 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_MAX_ROWS` | 1253 | `sync/` | P6 | offen | tests/test_server.py:8711 (direkt/dynamisch unklar); tests/test_server.py:8716 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 1254 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 1255 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_STALE_SECONDS` | 1256 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_LABELS` | 1264 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 1272 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 1273 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 1274 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 1275 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 1276 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 1277 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 1278 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 1279 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_DURATION_SECONDS` | 1280 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_MAX_ENTRIES` | 1281 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_STATE_KEY` | 1282 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_ENTRIES_KEY` | 1283 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 1285 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 1288 | `history/` | P5 | offen | tests/test_server.py:5588 (direkt/dynamisch unklar); tests/test_server.py:5599 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 1289 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 1290 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 1291 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 1292 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 1297 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 1302 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 1307 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 1311 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 1313 | `planning/` | P4 | offen | tests/test_server.py:363 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 1314 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 1315 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 1318 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 1329 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 1335 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 1344 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 1354 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1381 | `observability.py` | P1 | offen | tests/test_server.py:8009 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1402 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1445 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:281 (direkt/dynamisch unklar); tests/test_provider_review.py:187 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:197 (direkt/dynamisch unklar); tests/test_provider_review.py:320 (direkt/dynamisch unklar); tests/test_provider_review.py:329 (direkt/dynamisch unklar); tests/test_server.py:179 (direkt/dynamisch unklar) |
| Funktion | `database` | 1472 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:183 (direkt/dynamisch unklar); tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1011 (direkt/dynamisch unklar); tests/test_server.py:1032 (direkt/dynamisch unklar); tests/test_server.py:1041 (direkt/dynamisch unklar); tests/test_server.py:1055 (direkt/dynamisch unklar); tests/test_server.py:1067 (direkt/dynamisch unklar); tests/test_server.py:1081 (direkt/dynamisch unklar); tests/test_server.py:1090 (direkt/dynamisch unklar); tests/test_server.py:1099 (direkt/dynamisch unklar); tests/test_server.py:1106 (direkt/dynamisch unklar); tests/test_server.py:1117 (direkt/dynamisch unklar); tests/test_server.py:1128 (direkt/dynamisch unklar); tests/test_server.py:125 (direkt/dynamisch unklar); tests/test_server.py:1285 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1293 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1314 (direkt/dynamisch unklar); tests/test_server.py:1318 (direkt/dynamisch unklar); tests/test_server.py:1395 (direkt/dynamisch unklar); tests/test_server.py:1507 (direkt/dynamisch unklar); tests/test_server.py:156 (direkt/dynamisch unklar); tests/test_server.py:1644 (direkt/dynamisch unklar); tests/test_server.py:2529 (direkt/dynamisch unklar); tests/test_server.py:2590 (direkt/dynamisch unklar); tests/test_server.py:2603 (direkt/dynamisch unklar); tests/test_server.py:2659 (direkt/dynamisch unklar); tests/test_server.py:2682 (direkt/dynamisch unklar); tests/test_server.py:2811 (direkt/dynamisch unklar); tests/test_server.py:2824 (direkt/dynamisch unklar); tests/test_server.py:2829 (direkt/dynamisch unklar); tests/test_server.py:2848 (direkt/dynamisch unklar); tests/test_server.py:3027 (direkt/dynamisch unklar); tests/test_server.py:3107 (direkt/dynamisch unklar); tests/test_server.py:3395 (direkt/dynamisch unklar); tests/test_server.py:4551 (direkt/dynamisch unklar); tests/test_server.py:4630 (direkt/dynamisch unklar); tests/test_server.py:4921 (direkt/dynamisch unklar); tests/test_server.py:5053 (direkt/dynamisch unklar); tests/test_server.py:5076 (direkt/dynamisch unklar); tests/test_server.py:5099 (direkt/dynamisch unklar); tests/test_server.py:5121 (direkt/dynamisch unklar); tests/test_server.py:5135 (direkt/dynamisch unklar); tests/test_server.py:5141 (direkt/dynamisch unklar); tests/test_server.py:5158 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5488 (direkt/dynamisch unklar); tests/test_server.py:5530 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5641 (direkt/dynamisch unklar); tests/test_server.py:5883 (direkt/dynamisch unklar); tests/test_server.py:5895 (direkt/dynamisch unklar); tests/test_server.py:5914 (direkt/dynamisch unklar); tests/test_server.py:595 (direkt/dynamisch unklar); tests/test_server.py:5988 (direkt/dynamisch unklar); tests/test_server.py:6010 (direkt/dynamisch unklar); tests/test_server.py:6019 (direkt/dynamisch unklar); tests/test_server.py:6144 (direkt/dynamisch unklar); tests/test_server.py:639 (direkt/dynamisch unklar); tests/test_server.py:6436 (direkt/dynamisch unklar); tests/test_server.py:6499 (direkt/dynamisch unklar); tests/test_server.py:650 (direkt/dynamisch unklar); tests/test_server.py:6544 (direkt/dynamisch unklar); tests/test_server.py:6583 (direkt/dynamisch unklar); tests/test_server.py:6592 (direkt/dynamisch unklar); tests/test_server.py:664 (direkt/dynamisch unklar); tests/test_server.py:6768 (direkt/dynamisch unklar); tests/test_server.py:6777 (direkt/dynamisch unklar); tests/test_server.py:6787 (direkt/dynamisch unklar); tests/test_server.py:6938 (direkt/dynamisch unklar); tests/test_server.py:7732 (direkt/dynamisch unklar); tests/test_server.py:7971 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8430 (direkt/dynamisch unklar); tests/test_server.py:8564 (direkt/dynamisch unklar); tests/test_server.py:8700 (direkt/dynamisch unklar); tests/test_server.py:8714 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1478 | `db/schema.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_provider_review.py:37 (direkt/dynamisch unklar); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:112 (direkt/dynamisch unklar); tests/test_server.py:1170 (direkt/dynamisch unklar); tests/test_server.py:155 (direkt/dynamisch unklar); tests/test_server.py:178 (direkt/dynamisch unklar); tests/test_server.py:198 (direkt/dynamisch unklar); tests/test_server.py:2828 (direkt/dynamisch unklar); tests/test_server.py:2837 (direkt/dynamisch unklar); tests/test_server.py:2847 (direkt/dynamisch unklar); tests/test_server.py:3388 (direkt/dynamisch unklar); tests/test_server.py:6581 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1520 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1525 | `settings.py` | P1 | offen | tests/test_server.py:8682 (direkt/dynamisch unklar); tests/test_server.py:8698 (direkt/dynamisch unklar); tests/test_server.py:8712 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1537 | `settings.py` | P1 | offen | tests/test_server.py:8683 (direkt/dynamisch unklar); tests/test_server.py:8699 (direkt/dynamisch unklar); tests/test_server.py:8713 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1571 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1586 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1600 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1609 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1623 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1636 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1646 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1655 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1665 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1672 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1697 | `sync/` | P6 | offen | tests/test_audit_remediation.py:278 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:208 (direkt/dynamisch unklar); tests/test_server.py:210 (direkt/dynamisch unklar); tests/test_server.py:214 (direkt/dynamisch unklar); tests/test_server.py:225 (direkt/dynamisch unklar); tests/test_server.py:258 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1706 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:142 (direkt/dynamisch unklar); tests/test_provider_review.py:179 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1712 | `sync/` | P6 | offen | tests/test_server.py:975 (Monkeypatch/getattr/sys.modules); tests/test_server.py:984 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1717 | `sync/` | P6 | offen | tests/test_server.py:606 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1740 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1748 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1757 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1775 | `sync/` | P6 | offen | tests/test_server.py:618 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1802 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1811 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1818 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1828 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 1853 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 1867 | `sync/` | P6 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:203 (direkt/dynamisch unklar); tests/test_server.py:220 (direkt/dynamisch unklar); tests/test_server.py:247 (direkt/dynamisch unklar); tests/test_server.py:344 (Monkeypatch/getattr/sys.modules); tests/test_server.py:431 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4894 (direkt/dynamisch unklar); tests/test_server.py:4898 (direkt/dynamisch unklar); tests/test_server.py:527 (Monkeypatch/getattr/sys.modules); tests/test_server.py:587 (direkt/dynamisch unklar); tests/test_server.py:590 (direkt/dynamisch unklar); tests/test_server.py:605 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6343 (direkt/dynamisch unklar); tests/test_server.py:6352 (direkt/dynamisch unklar); tests/test_server.py:6371 (direkt/dynamisch unklar); tests/test_server.py:6380 (direkt/dynamisch unklar); tests/test_server.py:867 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8692 (direkt/dynamisch unklar); tests/test_server.py:893 (Monkeypatch/getattr/sys.modules); tests/test_server.py:938 (Monkeypatch/getattr/sys.modules); tests/test_server.py:986 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 1894 | `sync/` | P6 | offen | tests/test_server.py:209 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 1914 | `sync/` | P6 | offen | tests/test_audit_remediation.py:274 (direkt/dynamisch unklar); tests/test_audit_remediation.py:279 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:154 (direkt/dynamisch unklar); tests/test_server.py:206 (direkt/dynamisch unklar); tests/test_server.py:211 (direkt/dynamisch unklar); tests/test_server.py:221 (direkt/dynamisch unklar); tests/test_server.py:254 (direkt/dynamisch unklar); tests/test_server.py:6344 (direkt/dynamisch unklar); tests/test_server.py:6353 (direkt/dynamisch unklar); tests/test_server.py:6372 (direkt/dynamisch unklar); tests/test_server.py:6381 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 1935 | `sync/` | P6 | offen | tests/test_audit_remediation.py:241 (direkt/dynamisch unklar); tests/test_audit_remediation.py:276 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 1973 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 1979 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 1990 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 2010 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 2025 | `runtime/` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 2042 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 2055 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 2064 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 2071 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 2088 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 2100 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 2112 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:138 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:167 (Monkeypatch/getattr/sys.modules); tests/test_server.py:212 (Monkeypatch/getattr/sys.modules); tests/test_server.py:223 (Monkeypatch/getattr/sys.modules); tests/test_server.py:236 (direkt/dynamisch unklar); tests/test_server.py:256 (Monkeypatch/getattr/sys.modules); tests/test_server.py:553 (direkt/dynamisch unklar); tests/test_server.py:554 (direkt/dynamisch unklar); tests/test_server.py:566 (direkt/dynamisch unklar); tests/test_server.py:579 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 2135 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 2144 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 2164 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 2184 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 2202 | `sync/` | P6 | offen | tests/test_provider_review.py:139 (direkt/dynamisch unklar); tests/test_provider_review.py:168 (direkt/dynamisch unklar); tests/test_server.py:213 (direkt/dynamisch unklar); tests/test_server.py:224 (direkt/dynamisch unklar); tests/test_server.py:257 (direkt/dynamisch unklar); tests/test_server.py:6344 (direkt/dynamisch unklar); tests/test_server.py:6353 (direkt/dynamisch unklar); tests/test_server.py:6372 (direkt/dynamisch unklar); tests/test_server.py:6381 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 2212 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 2227 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `resolve_sync_job` | 2239 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_scheduled_provider_retry_at` | 2262 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_inputs` | 2281 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_last_good_state` | 2315 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_fallback_error_code` | 2325 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_error_code` | 2329 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_status` | 2337 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `provider_freshness_state` | 2358 | `settings.py` | P1 | offen | tests/test_server.py:6141 (direkt/dynamisch unklar); tests/test_server.py:8679 (direkt/dynamisch unklar); tests/test_server.py:8684 (direkt/dynamisch unklar); tests/test_server.py:8689 (direkt/dynamisch unklar); tests/test_server.py:8696 (direkt/dynamisch unklar); tests/test_server.py:8706 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 2399 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 2413 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 2424 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 2448 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 2453 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 2465 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 2475 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 2492 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2531 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2563 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3155 (direkt/dynamisch unklar); tests/test_server.py:5571 (direkt/dynamisch unklar); tests/test_server.py:5660 (direkt/dynamisch unklar); tests/test_server.py:5709 (direkt/dynamisch unklar); tests/test_server.py:8633 (direkt/dynamisch unklar); tests/test_server.py:8653 (direkt/dynamisch unklar); tests/test_server.py:8662 (direkt/dynamisch unklar); tests/test_server.py:8665 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2574 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2586 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2600 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2616 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8642 (direkt/dynamisch unklar); tests/test_server.py:8648 (direkt/dynamisch unklar); tests/test_server.py:8654 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2654 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2674 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2684 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2709 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2730 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2740 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2749 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2775 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2791 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2811 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2820 | `history/` | P5 | offen | tests/test_server.py:3162 (direkt/dynamisch unklar); tests/test_server.py:5578 (direkt/dynamisch unklar); tests/test_server.py:5713 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2835 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:237 (direkt/dynamisch unklar); tests/test_audit_remediation.py:287 (direkt/dynamisch unklar); tests/test_audit_remediation.py:288 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar); tests/test_provider_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:1188 (direkt/dynamisch unklar); tests/test_server.py:1208 (direkt/dynamisch unklar); tests/test_server.py:1215 (direkt/dynamisch unklar); tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:199 (direkt/dynamisch unklar); tests/test_server.py:200 (direkt/dynamisch unklar); tests/test_server.py:2838 (direkt/dynamisch unklar); tests/test_server.py:2839 (direkt/dynamisch unklar); tests/test_server.py:4161 (direkt/dynamisch unklar); tests/test_server.py:4162 (direkt/dynamisch unklar); tests/test_server.py:4445 (direkt/dynamisch unklar); tests/test_server.py:4568 (direkt/dynamisch unklar); tests/test_server.py:6098 (direkt/dynamisch unklar); tests/test_server.py:6110 (direkt/dynamisch unklar); tests/test_server.py:6111 (direkt/dynamisch unklar); tests/test_server.py:6214 (direkt/dynamisch unklar); tests/test_server.py:6233 (direkt/dynamisch unklar); tests/test_server.py:6237 (direkt/dynamisch unklar); tests/test_server.py:6572 (direkt/dynamisch unklar); tests/test_server.py:6591 (direkt/dynamisch unklar); tests/test_server.py:6649 (direkt/dynamisch unklar); tests/test_server.py:7744 (direkt/dynamisch unklar); tests/test_server.py:7762 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 2842 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 2843 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 2844 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 2845 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_CALENDAR_WINDOW_DAYS` | 2846 | `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | P0 (Zuordnung offen) | offen | tests/test_server.py:2641 (direkt/dynamisch unklar) |
| Globale Bindung | `ICAL_MAX_RECURRENCE_COUNT` | 2847 | `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | P0 (Zuordnung offen) | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_MAX_RECURRENCE_PERIODS` | 2848 | `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | P0 (Zuordnung offen) | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 2849 | `planning/` | P4 | offen | tests/test_server.py:2704 (direkt/dynamisch unklar); tests/test_server.py:2714 (direkt/dynamisch unklar); tests/test_server.py:2739 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 2850 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 2851 | `planning/` | P4 | offen | tests/test_server.py:2316 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 2852 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 2855 | `planning/` | P4 | offen | tests/test_server.py:3646 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 2856 | `planning/` | P4 | offen | tests/test_server.py:3647 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 2857 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 2858 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 2859 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 2860 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 2861 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 2862 | `coach/` | P7 | offen | tests/test_server.py:5349 (direkt/dynamisch unklar); tests/test_server.py:5360 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 2863 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 2876 | `sync/` | P6 | offen | tests/test_server.py:6035 (direkt/dynamisch unklar); tests/test_server.py:6037 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 2887 | `sync/` | P6 | offen | tests/test_server.py:6034 (direkt/dynamisch unklar); tests/test_server.py:6036 (direkt/dynamisch unklar); tests/test_server.py:6062 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 2899 | `sync/` | P6 | offen | tests/test_server.py:6038 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 2910 | `settings.py` | P1 | offen | tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:223 (direkt/dynamisch unklar); tests/test_provider_review.py:247 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 2915 | `settings.py` | P1 | offen | tests/test_provider_review.py:210 (direkt/dynamisch unklar); tests/test_provider_review.py:211 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 2921 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:326 (direkt/dynamisch unklar); tests/test_server.py:1186 (direkt/dynamisch unklar); tests/test_server.py:1206 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1391 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1393 (direkt/dynamisch unklar); tests/test_server.py:1394 (direkt/dynamisch unklar); tests/test_server.py:1486 (direkt/dynamisch unklar); tests/test_server.py:1498 (direkt/dynamisch unklar); tests/test_server.py:1530 (direkt/dynamisch unklar); tests/test_server.py:1638 (direkt/dynamisch unklar); tests/test_server.py:1853 (direkt/dynamisch unklar); tests/test_server.py:1854 (direkt/dynamisch unklar); tests/test_server.py:1855 (direkt/dynamisch unklar); tests/test_server.py:1856 (direkt/dynamisch unklar); tests/test_server.py:1857 (direkt/dynamisch unklar); tests/test_server.py:196 (direkt/dynamisch unklar); tests/test_server.py:197 (direkt/dynamisch unklar); tests/test_server.py:2834 (direkt/dynamisch unklar); tests/test_server.py:2835 (direkt/dynamisch unklar); tests/test_server.py:3259 (direkt/dynamisch unklar); tests/test_server.py:3283 (direkt/dynamisch unklar); tests/test_server.py:3294 (direkt/dynamisch unklar); tests/test_server.py:3342 (direkt/dynamisch unklar); tests/test_server.py:3449 (direkt/dynamisch unklar); tests/test_server.py:3481 (direkt/dynamisch unklar); tests/test_server.py:3500 (direkt/dynamisch unklar); tests/test_server.py:3541 (direkt/dynamisch unklar); tests/test_server.py:3561 (direkt/dynamisch unklar); tests/test_server.py:4211 (direkt/dynamisch unklar); tests/test_server.py:4217 (direkt/dynamisch unklar); tests/test_server.py:4501 (direkt/dynamisch unklar); tests/test_server.py:4525 (direkt/dynamisch unklar); tests/test_server.py:4538 (direkt/dynamisch unklar); tests/test_server.py:4618 (direkt/dynamisch unklar); tests/test_server.py:4640 (direkt/dynamisch unklar); tests/test_server.py:5416 (direkt/dynamisch unklar); tests/test_server.py:5452 (direkt/dynamisch unklar); tests/test_server.py:5947 (direkt/dynamisch unklar); tests/test_server.py:6103 (direkt/dynamisch unklar); tests/test_server.py:6565 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6640 (direkt/dynamisch unklar); tests/test_server.py:6641 (direkt/dynamisch unklar); tests/test_server.py:7723 (direkt/dynamisch unklar); tests/test_server.py:7724 (direkt/dynamisch unklar); tests/test_server.py:7741 (direkt/dynamisch unklar); tests/test_server.py:7756 (direkt/dynamisch unklar); tests/test_server.py:7830 (direkt/dynamisch unklar); tests/test_server.py:7946 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar); tests/test_server.py:8504 (direkt/dynamisch unklar) |
| Funktion | `_safe_diagnostic_context` | 2929 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_mapping_shape` | 2941 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_sequence_shape` | 2953 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_response_shape` | 2960 | `observability.py` | P1 | offen | tests/test_server.py:8583 (direkt/dynamisch unklar); tests/test_server.py:8588 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_response` | 2977 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_diagnostic_error` | 2982 | `observability.py` | P1 | offen | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 3000 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 3015 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_capture_state` | 3032 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_capture_status` | 3040 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7908 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_entries` | 3062 | `observability.py` | P1 | offen | tests/test_server.py:7901 (direkt/dynamisch unklar); tests/test_server.py:8270 (direkt/dynamisch unklar) |
| Funktion | `set_diagnostic_capture` | 3072 | `observability.py` | P1 | offen | tests/test_server.py:7887 (direkt/dynamisch unklar); tests/test_server.py:7907 (direkt/dynamisch unklar); tests/test_server.py:8264 (direkt/dynamisch unklar) |
| Funktion | `capture_diagnostic_event` | 3087 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 3101 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:217 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar); tests/test_server.py:5421 (direkt/dynamisch unklar); tests/test_server.py:5423 (direkt/dynamisch unklar); tests/test_server.py:6650 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 3109 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 3113 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4154 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 3121 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 3133 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 3148 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 3158 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 3169 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 3178 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 3193 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 3207 | `activities/` | P3 | offen | tests/test_server.py:3612 (direkt/dynamisch unklar); tests/test_server.py:3620 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 3219 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 3235 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 3250 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7632 (direkt/dynamisch unklar); tests/test_server.py:7643 (direkt/dynamisch unklar); tests/test_server.py:7651 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 3257 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3425 (direkt/dynamisch unklar); tests/test_server.py:7633 (direkt/dynamisch unklar); tests/test_server.py:7659 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 3264 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 3279 | `activities/` | P3 | offen | tests/test_server.py:7698 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 3302 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 3315 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 3333 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 3351 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7674 (direkt/dynamisch unklar); tests/test_server.py:7687 (direkt/dynamisch unklar); tests/test_server.py:7699 (direkt/dynamisch unklar); tests/test_server.py:7711 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 3366 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3428 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 3381 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 3394 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 3406 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 3409 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 3413 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 3419 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 3424 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 3433 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3336 (direkt/dynamisch unklar); tests/test_server.py:3337 (direkt/dynamisch unklar); tests/test_server.py:3338 (direkt/dynamisch unklar); tests/test_server.py:3339 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 3452 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 3465 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 3469 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 3487 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 3501 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 3517 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 3523 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 3531 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 3544 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 3557 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 3564 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 3582 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 3587 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 3613 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 3623 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 3632 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3443 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 3642 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3657 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3666 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3671 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3679 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3693 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3704 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3723 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3734 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3751 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3775 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3784 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3795 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3814 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:292 (direkt/dynamisch unklar); tests/test_provider_review.py:307 (direkt/dynamisch unklar); tests/test_server.py:3311 (direkt/dynamisch unklar); tests/test_server.py:3368 (direkt/dynamisch unklar); tests/test_server.py:3401 (direkt/dynamisch unklar); tests/test_server.py:3428 (direkt/dynamisch unklar); tests/test_server.py:3435 (direkt/dynamisch unklar); tests/test_server.py:3475 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3836 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 3851 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 3856 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 3872 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:302 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 3890 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 3909 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 3938 | `planning/` | P4 | offen | tests/test_server.py:3254 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 3955 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 3963 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 3991 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 3998 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 4022 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 4031 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 4048 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 4064 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 4069 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4111 (direkt/dynamisch unklar); tests/test_server.py:4115 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 4070 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 4073 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4114 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 4081 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4113 (direkt/dynamisch unklar); tests/test_server.py:4118 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 4090 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4112 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 4103 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4117 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 4108 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 4130 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 4140 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 4144 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4166 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 4159 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 4160 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 4163 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 4182 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 4196 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 4207 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4156 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 4218 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 4226 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 4231 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 4235 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 4253 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 4263 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 4267 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4142 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 4287 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 4298 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 4316 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:4121 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 4353 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 4358 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4210 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 4366 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 4379 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 4403 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 4432 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 4456 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4202 (direkt/dynamisch unklar); tests/test_server.py:4203 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 4469 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 4481 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 4511 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 4540 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 4547 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 4606 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 4629 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:242 (direkt/dynamisch unklar); tests/test_server.py:234 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4155 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8578 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4671 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:359 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4678 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4689 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:4209 (direkt/dynamisch unklar); tests/test_server.py:4221 (direkt/dynamisch unklar); tests/test_server.py:7831 (direkt/dynamisch unklar); tests/test_server.py:8579 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4729 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:280 (direkt/dynamisch unklar); tests/test_server.py:3274 (direkt/dynamisch unklar); tests/test_server.py:3288 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4752 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1691 (direkt/dynamisch unklar); tests/test_server.py:1723 (direkt/dynamisch unklar); tests/test_server.py:4522 (direkt/dynamisch unklar); tests/test_server.py:4523 (direkt/dynamisch unklar); tests/test_server.py:4524 (direkt/dynamisch unklar); tests/test_server.py:5239 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4759 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4766 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4769 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4781 | `athlete/` | P3 | offen | tests/test_server.py:1137 (direkt/dynamisch unklar); tests/test_server.py:1600 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4790 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1610 (direkt/dynamisch unklar); tests/test_server.py:6756 (direkt/dynamisch unklar); tests/test_server.py:8646 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4799 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:144 (direkt/dynamisch unklar); tests/test_audit_remediation.py:76 (direkt/dynamisch unklar); tests/test_audit_remediation.py:79 (direkt/dynamisch unklar); tests/test_audit_remediation.py:87 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1160 (direkt/dynamisch unklar); tests/test_server.py:1169 (direkt/dynamisch unklar); tests/test_server.py:1185 (direkt/dynamisch unklar); tests/test_server.py:1187 (direkt/dynamisch unklar); tests/test_server.py:1191 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1207 (direkt/dynamisch unklar); tests/test_server.py:1211 (direkt/dynamisch unklar); tests/test_server.py:1219 (direkt/dynamisch unklar); tests/test_server.py:1226 (direkt/dynamisch unklar); tests/test_server.py:1245 (direkt/dynamisch unklar); tests/test_server.py:149 (direkt/dynamisch unklar); tests/test_server.py:1512 (direkt/dynamisch unklar); tests/test_server.py:1529 (direkt/dynamisch unklar); tests/test_server.py:1572 (direkt/dynamisch unklar); tests/test_server.py:1593 (direkt/dynamisch unklar); tests/test_server.py:1595 (direkt/dynamisch unklar); tests/test_server.py:1606 (direkt/dynamisch unklar); tests/test_server.py:2501 (direkt/dynamisch unklar); tests/test_server.py:6709 (direkt/dynamisch unklar); tests/test_server.py:6737 (direkt/dynamisch unklar); tests/test_server.py:7306 (direkt/dynamisch unklar); tests/test_server.py:7451 (direkt/dynamisch unklar); tests/test_server.py:8631 (direkt/dynamisch unklar); tests/test_server.py:8632 (direkt/dynamisch unklar); tests/test_server.py:8661 (direkt/dynamisch unklar); tests/test_server.py:8678 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4813 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4823 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4830 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4833 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 4845 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 4857 | `athlete/` | P3 | offen | tests/test_server.py:1617 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 4877 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2713 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 4882 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1580 (direkt/dynamisch unklar); tests/test_server.py:1589 (direkt/dynamisch unklar); tests/test_server.py:1619 (direkt/dynamisch unklar); tests/test_server.py:1623 (direkt/dynamisch unklar); tests/test_server.py:1637 (direkt/dynamisch unklar); tests/test_server.py:1668 (direkt/dynamisch unklar); tests/test_server.py:2702 (direkt/dynamisch unklar); tests/test_server.py:2723 (direkt/dynamisch unklar); tests/test_server.py:2749 (direkt/dynamisch unklar); tests/test_server.py:2768 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 4890 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 4913 | `athlete/` | P3 | offen | tests/test_server.py:1587 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 4923 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 4930 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 4944 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2363 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 4949 | `activities/` | P3 | offen | tests/test_server.py:2360 (direkt/dynamisch unklar); tests/test_server.py:2362 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 4961 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2330 (direkt/dynamisch unklar); tests/test_server.py:2343 (direkt/dynamisch unklar); tests/test_server.py:2353 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 4978 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 4985 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 4999 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 5011 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 5033 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 5045 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 5059 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 5065 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3210 (direkt/dynamisch unklar); tests/test_server.py:3214 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 5075 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3212 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 5082 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 5095 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3196 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 5116 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:45 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:58 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:6459 (direkt/dynamisch unklar); tests/test_server.py:646 (direkt/dynamisch unklar); tests/test_server.py:6541 (direkt/dynamisch unklar); tests/test_server.py:656 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:6830 (direkt/dynamisch unklar); tests/test_server.py:6864 (direkt/dynamisch unklar); tests/test_server.py:6901 (direkt/dynamisch unklar); tests/test_server.py:6948 (direkt/dynamisch unklar); tests/test_server.py:6985 (direkt/dynamisch unklar); tests/test_server.py:6993 (direkt/dynamisch unklar); tests/test_server.py:7020 (direkt/dynamisch unklar); tests/test_server.py:7048 (direkt/dynamisch unklar) |
| Funktion | `_resolve_calendar_addresses` | 5121 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2566 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_calendar_feed_request` | 5136 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_remaining` | 5159 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_fetch_calendar_address` | 5166 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_failure_log` | 5201 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `fetch_calendar_feed` | 5216 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2536 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2571 (direkt/dynamisch unklar); tests/test_server.py:2584 (direkt/dynamisch unklar); tests/test_server.py:2621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2665 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_ical_temporal_value` | 5271 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_TRAINING_MARKER` | 5301 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_INTENSITY_MARKER` | 5302 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_SHORT_ONLY_MARKER` | 5303 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_TRAINING_MARKERS` | 5304 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_description_contains` | 5307 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_impact` | 5311 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_relevant` | 5316 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_no_intensity` | 5322 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_short_only` | 5327 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_DAY_NUMBERS` | 5332 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_values` | 5335 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_integer` | 5350 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_byday` | 5367 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_bydays` | 5381 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_until` | 5398 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rrule` | 5407 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_shift_local` | 5447 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekday_ordinal` | 5451 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_byday` | 5455 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_date_filters` | 5471 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_dates` | 5484 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_apply_bysetpos` | 5498 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_recurrence_start` | 5510 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_record` | 5515 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_daily_recurrence_starts` | 5534 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_candidate_starts` | 5556 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_recurrence_starts` | 5568 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_period` | 5594 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_candidates` | 5604 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_marker` | 5609 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_first_period_index` | 5613 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_recurrence_starts` | 5622 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_starts` | 5647 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_duration` | 5657 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_occurrence_overlaps_window` | 5668 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rule_starts` | 5673 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rdates` | 5686 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_instances` | 5693 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_calendar_window` | 5710 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_property_parameters` | 5718 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_dates` | 5729 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_temporal_property` | 5744 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_id` | 5754 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_event_property` | 5761 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_append_event` | 5782 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_skip_nested_event_line` | 5791 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_parsed_events` | 5799 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_exception_starts` | 5823 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_event_instances` | 5831 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_expanded_events` | 5845 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `parse_ical_calendar` | 5858 | `providers/` | P2 | offen | tests/test_audit_remediation.py:160 (direkt/dynamisch unklar); tests/test_audit_remediation.py:164 (direkt/dynamisch unklar); tests/test_server.py:2394 (direkt/dynamisch unklar); tests/test_server.py:2425 (direkt/dynamisch unklar); tests/test_server.py:2453 (direkt/dynamisch unklar); tests/test_server.py:2459 (direkt/dynamisch unklar); tests/test_server.py:2466 (direkt/dynamisch unklar); tests/test_server.py:2473 (direkt/dynamisch unklar); tests/test_server.py:2478 (direkt/dynamisch unklar); tests/test_server.py:2482 (direkt/dynamisch unklar); tests/test_server.py:2493 (direkt/dynamisch unklar); tests/test_server.py:2508 (direkt/dynamisch unklar); tests/test_server.py:2521 (direkt/dynamisch unklar); tests/test_server.py:2525 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_url` | 5864 | `providers/` | P2 | offen | tests/test_server.py:2544 (direkt/dynamisch unklar); tests/test_server.py:2553 (direkt/dynamisch unklar); tests/test_server.py:2672 (direkt/dynamisch unklar); tests/test_server.py:2674 (direkt/dynamisch unklar); tests/test_server.py:7822 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_external_calendar_events` | 5880 | `providers/` | P2 | offen | tests/test_server.py:2539 (direkt/dynamisch unklar); tests/test_server.py:2595 (direkt/dynamisch unklar); tests/test_server.py:2636 (direkt/dynamisch unklar); tests/test_server.py:2655 (direkt/dynamisch unklar); tests/test_server.py:2668 (direkt/dynamisch unklar); tests/test_server.py:3116 (direkt/dynamisch unklar); tests/test_server.py:3118 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 5891 | `providers/` | P2 | offen | tests/test_server.py:2631 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 5906 | `sync/` | P6 | offen | tests/test_server.py:2538 (direkt/dynamisch unklar); tests/test_server.py:2626 (direkt/dynamisch unklar); tests/test_server.py:2651 (direkt/dynamisch unklar); tests/test_server.py:2667 (direkt/dynamisch unklar); tests/test_server.py:7826 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 5952 | `providers/` | P2 | offen | tests/test_audit_remediation.py:163 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 5967 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 5971 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 5975 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 5981 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 5987 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 5995 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 6013 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 6030 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 6057 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 6064 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 6078 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 6110 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 6119 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 6130 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 6149 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 6161 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 6167 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 6180 | `performance/` | P3 | offen | tests/test_server.py:4212 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 6192 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 6196 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 6206 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 6215 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 6225 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 6236 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 6245 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 6265 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 6279 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1649 (direkt/dynamisch unklar); tests/test_server.py:3118 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 6303 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 6312 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 6324 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 6337 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 6352 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 6358 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 6369 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 6377 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 6388 | `coach/context.py` | P7 | offen | tests/test_server.py:1214 (direkt/dynamisch unklar); tests/test_server.py:3606 (direkt/dynamisch unklar); tests/test_server.py:6331 (direkt/dynamisch unklar); tests/test_server.py:6359 (direkt/dynamisch unklar); tests/test_server.py:6403 (direkt/dynamisch unklar); tests/test_server.py:6421 (direkt/dynamisch unklar); tests/test_server.py:6430 (direkt/dynamisch unklar); tests/test_server.py:6494 (direkt/dynamisch unklar); tests/test_server.py:6717 (direkt/dynamisch unklar); tests/test_server.py:6784 (direkt/dynamisch unklar); tests/test_server.py:6834 (direkt/dynamisch unklar); tests/test_server.py:6870 (direkt/dynamisch unklar); tests/test_server.py:6909 (direkt/dynamisch unklar); tests/test_server.py:6992 (direkt/dynamisch unklar); tests/test_server.py:6998 (direkt/dynamisch unklar); tests/test_server.py:7024 (direkt/dynamisch unklar); tests/test_server.py:7043 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 6405 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 6427 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 6439 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 6440 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 6445 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 6455 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 6473 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 6485 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 6498 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 6510 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 6529 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:39 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1073 (direkt/dynamisch unklar); tests/test_server.py:418 (direkt/dynamisch unklar); tests/test_server.py:636 (direkt/dynamisch unklar); tests/test_server.py:6415 (direkt/dynamisch unklar); tests/test_server.py:6441 (direkt/dynamisch unklar); tests/test_server.py:6753 (direkt/dynamisch unklar); tests/test_server.py:6758 (direkt/dynamisch unklar); tests/test_server.py:6792 (direkt/dynamisch unklar); tests/test_server.py:6933 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 6537 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:51 (direkt/dynamisch unklar); tests/test_audit_remediation.py:63 (direkt/dynamisch unklar); tests/test_server.py:6773 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 6567 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 6588 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 6611 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 6626 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 6636 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 6642 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3189 (direkt/dynamisch unklar); tests/test_server.py:3190 (direkt/dynamisch unklar); tests/test_server.py:3191 (direkt/dynamisch unklar); tests/test_server.py:3192 (direkt/dynamisch unklar); tests/test_server.py:3193 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 6647 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 6662 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_server.py:6439 (direkt/dynamisch unklar); tests/test_server.py:6771 (direkt/dynamisch unklar); tests/test_server.py:6786 (direkt/dynamisch unklar); tests/test_server.py:6863 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 6666 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3218 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 6686 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3206 (direkt/dynamisch unklar); tests/test_server.py:3207 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 6702 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 6712 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3244 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 6719 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3245 (direkt/dynamisch unklar); tests/test_server.py:3246 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 6725 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3230 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 6753 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 6759 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 6768 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 6778 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6928 (direkt/dynamisch unklar); tests/test_server.py:6945 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 6818 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 6832 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 6845 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 6871 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 6897 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 6905 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 6913 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 6917 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 6955 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 6963 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 6970 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 6985 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 6997 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 7009 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 7016 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 7020 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 7053 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 7076 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 7095 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 7112 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 7120 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 7150 | `sync/` | P6 | offen | tests/test_audit_remediation.py:44 (direkt/dynamisch unklar); tests/test_audit_remediation.py:55 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_audit_remediation.py:71 (direkt/dynamisch unklar); tests/test_server.py:6414 (direkt/dynamisch unklar); tests/test_server.py:6422 (direkt/dynamisch unklar); tests/test_server.py:6458 (direkt/dynamisch unklar); tests/test_server.py:6628 (direkt/dynamisch unklar); tests/test_server.py:6825 (direkt/dynamisch unklar); tests/test_server.py:6857 (direkt/dynamisch unklar); tests/test_server.py:6858 (direkt/dynamisch unklar); tests/test_server.py:6895 (direkt/dynamisch unklar); tests/test_server.py:6927 (direkt/dynamisch unklar); tests/test_server.py:6943 (direkt/dynamisch unklar); tests/test_server.py:6946 (direkt/dynamisch unklar); tests/test_server.py:6982 (direkt/dynamisch unklar); tests/test_server.py:7015 (direkt/dynamisch unklar); tests/test_server.py:7042 (direkt/dynamisch unklar); tests/test_server.py:7044 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_RATE_LIMIT_HEADERS` | 7206 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_STATUS_KEY` | 7215 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `GEMINI_STATUS_KEY` | 7216 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 7217 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `_retry_after_seconds` | 7220 | `providers/http.py` | P2 | offen | tests/test_server.py:8149 (direkt/dynamisch unklar) |
| Funktion | `_safe_openai_error_token` | 7234 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_diagnostic_details` | 7242 | `observability.py` | P1 | offen | tests/test_server.py:8212 (direkt/dynamisch unklar); tests/test_server.py:8235 (direkt/dynamisch unklar) |
| Funktion | `_openai_error_tokens` | 7265 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_invalid_input_state` | 7275 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_conversation_error` | 7283 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_billing_error` | 7294 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_error_reason` | 7305 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_details` | 7325 | `providers/` | P2 | offen | tests/test_server.py:8137 (direkt/dynamisch unklar); tests/test_server.py:8142 (direkt/dynamisch unklar); tests/test_server.py:8210 (direkt/dynamisch unklar); tests/test_server.py:8233 (direkt/dynamisch unklar); tests/test_server.py:8250 (direkt/dynamisch unklar) |
| Funktion | `safe_openai_log_reason` | 7341 | `observability.py` | P1 | offen | tests/test_server.py:8181 (direkt/dynamisch unklar); tests/test_server.py:8182 (direkt/dynamisch unklar) |
| Funktion | `_provider_error_payload` | 7364 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_tokens` | 7373 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_reason` | 7381 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_error_details` | 7395 | `providers/` | P2 | offen | tests/test_server.py:4648 (direkt/dynamisch unklar); tests/test_server.py:4650 (direkt/dynamisch unklar); tests/test_server.py:4651 (direkt/dynamisch unklar) |
| Funktion | `record_openai_status` | 7401 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_success` | 7416 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_rate_limits` | 7426 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_body` | 7438 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 7446 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 7454 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 7466 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 7471 | `coach/context.py` | P7 | offen | tests/test_server.py:7940 (direkt/dynamisch unklar) |
| Funktion | `_read_http_error_body` | 7481 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_urlopen_interruptibly` | 7492 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_body` | 7519 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_parts` | 7527 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_http_request_started` | 7561 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_http_response` | 7574 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 7589 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 7630 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 7649 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 7699 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 7734 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 7739 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 7767 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1737 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4370 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4439 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4578 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4668 (direkt/dynamisch unklar); tests/test_server.py:4709 (direkt/dynamisch unklar); tests/test_server.py:4746 (direkt/dynamisch unklar); tests/test_server.py:4779 (direkt/dynamisch unklar); tests/test_server.py:4839 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7452 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7846 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7882 (direkt/dynamisch unklar); tests/test_server.py:7916 (direkt/dynamisch unklar); tests/test_server.py:7933 (direkt/dynamisch unklar); tests/test_server.py:8057 (direkt/dynamisch unklar); tests/test_server.py:8093 (direkt/dynamisch unklar); tests/test_server.py:8121 (direkt/dynamisch unklar); tests/test_server.py:8162 (direkt/dynamisch unklar); tests/test_server.py:8506 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 7802 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 7814 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 7823 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 7831 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 7835 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 7841 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 7853 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 7858 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 7884 | `weather/` | P3 | offen | tests/test_server.py:1148 (direkt/dynamisch unklar); tests/test_server.py:1154 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 7894 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 7918 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 7933 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 7952 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 7967 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 7981 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 8002 | `weather/` | P3 | offen | tests/test_server.py:7495 (direkt/dynamisch unklar); tests/test_server.py:7502 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 8049 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 8065 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 8075 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 8096 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 8116 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 8120 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 8143 | `weather/` | P3 | offen | tests/test_audit_remediation.py:106 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:81 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1166 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1192 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1220 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1234 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1253 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1520 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1536 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 8155 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 8166 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 8193 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 8201 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 8214 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 8250 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 8269 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 8275 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 8297 | `weather/` | P3 | offen | tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_audit_remediation.py:147 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:82 (direkt/dynamisch unklar); tests/test_server.py:1167 (direkt/dynamisch unklar); tests/test_server.py:1168 (direkt/dynamisch unklar); tests/test_server.py:1254 (direkt/dynamisch unklar); tests/test_server.py:1255 (direkt/dynamisch unklar); tests/test_server.py:1256 (direkt/dynamisch unklar); tests/test_server.py:1546 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2982 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7457 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 8315 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 8333 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 8348 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 8355 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 8371 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 8399 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 8412 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 8432 | `sync/` | P6 | offen | tests/test_audit_remediation.py:148 (direkt/dynamisch unklar); tests/test_server.py:1235 (direkt/dynamisch unklar); tests/test_server.py:1236 (direkt/dynamisch unklar); tests/test_server.py:1237 (direkt/dynamisch unklar); tests/test_server.py:1523 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 8448 | `planning/` | P4 | offen | tests/test_server.py:7469 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 8460 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 8473 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 8478 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 8483 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 8487 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 8491 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 8499 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 8515 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 8534 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 8538 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 8547 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 8559 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 8580 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 8607 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 8622 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 8635 | `planning/` | P4 | offen | tests/test_server.py:2929 (direkt/dynamisch unklar); tests/test_server.py:2931 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 8673 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 8694 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 8714 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 8732 | `planning/` | P4 | offen | tests/test_server.py:2894 (direkt/dynamisch unklar); tests/test_server.py:2954 (direkt/dynamisch unklar); tests/test_server.py:2993 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 8742 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:2955 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 8766 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 8786 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 8792 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 8815 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 8825 | `planning/` | P4 | offen | tests/test_server.py:2854 (direkt/dynamisch unklar); tests/test_server.py:3571 (direkt/dynamisch unklar); tests/test_server.py:6700 (direkt/dynamisch unklar); tests/test_server.py:7068 (direkt/dynamisch unklar); tests/test_server.py:7097 (direkt/dynamisch unklar); tests/test_server.py:7226 (direkt/dynamisch unklar); tests/test_server.py:7250 (direkt/dynamisch unklar); tests/test_server.py:7271 (direkt/dynamisch unklar); tests/test_server.py:7287 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 8863 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 8864 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 8869 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 8872 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 8881 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 8885 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 8894 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 8919 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 8926 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 8937 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3801 (direkt/dynamisch unklar); tests/test_server.py:3818 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 8951 | `planning/` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:3083 (direkt/dynamisch unklar); tests/test_server.py:3175 (direkt/dynamisch unklar); tests/test_server.py:3251 (direkt/dynamisch unklar); tests/test_server.py:3837 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 8974 | `planning/` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 8987 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3763 (direkt/dynamisch unklar); tests/test_server.py:3813 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 9014 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 9024 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 9034 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 9041 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 9059 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 9069 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 9082 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 9095 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 9110 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 9119 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:3586 (direkt/dynamisch unklar); tests/test_server.py:3591 (direkt/dynamisch unklar); tests/test_server.py:3592 (direkt/dynamisch unklar); tests/test_server.py:3602 (direkt/dynamisch unklar); tests/test_server.py:3607 (direkt/dynamisch unklar); tests/test_server.py:5042 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 9134 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 9147 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 9171 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 9182 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 9197 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1542 (direkt/dynamisch unklar); tests/test_server.py:1559 (direkt/dynamisch unklar); tests/test_server.py:2599 (direkt/dynamisch unklar); tests/test_server.py:2678 (direkt/dynamisch unklar); tests/test_server.py:2698 (direkt/dynamisch unklar); tests/test_server.py:2745 (direkt/dynamisch unklar); tests/test_server.py:2764 (direkt/dynamisch unklar); tests/test_server.py:2775 (direkt/dynamisch unklar); tests/test_server.py:2807 (direkt/dynamisch unklar); tests/test_server.py:360 (direkt/dynamisch unklar); tests/test_server.py:3785 (direkt/dynamisch unklar); tests/test_server.py:3870 (direkt/dynamisch unklar); tests/test_server.py:3898 (direkt/dynamisch unklar); tests/test_server.py:3919 (direkt/dynamisch unklar); tests/test_server.py:3921 (direkt/dynamisch unklar); tests/test_server.py:3928 (direkt/dynamisch unklar); tests/test_server.py:5553 (direkt/dynamisch unklar); tests/test_server.py:5563 (direkt/dynamisch unklar); tests/test_server.py:5591 (direkt/dynamisch unklar); tests/test_server.py:5836 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6302 (direkt/dynamisch unklar); tests/test_server.py:773 (direkt/dynamisch unklar); tests/test_server.py:806 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 9214 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5557 (direkt/dynamisch unklar); tests/test_server.py:5568 (direkt/dynamisch unklar); tests/test_server.py:5584 (direkt/dynamisch unklar); tests/test_server.py:5596 (direkt/dynamisch unklar); tests/test_server.py:5612 (direkt/dynamisch unklar); tests/test_server.py:5635 (direkt/dynamisch unklar); tests/test_server.py:5657 (direkt/dynamisch unklar); tests/test_server.py:800 (direkt/dynamisch unklar); tests/test_server.py:828 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 9222 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 9230 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 9235 | `planning/` | P4 | offen | tests/test_server.py:5559 (direkt/dynamisch unklar); tests/test_server.py:5569 (direkt/dynamisch unklar); tests/test_server.py:812 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 9252 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 9257 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 9269 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 9287 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 9316 | `planning/` | P4 | offen | tests/test_audit_remediation.py:224 (direkt/dynamisch unklar); tests/test_server.py:1573 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 9328 | `planning/` | P4 | offen | tests/test_server.py:2719 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 9345 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7734 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 9362 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 9387 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 9401 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 9410 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 9428 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 9442 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 9450 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 9468 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 9477 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 9491 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 9506 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 9523 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 9540 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 9564 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 9596 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 9622 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 9643 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 9651 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 9670 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 9693 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1550 (direkt/dynamisch unklar); tests/test_server.py:1567 (direkt/dynamisch unklar); tests/test_server.py:2608 (direkt/dynamisch unklar); tests/test_server.py:2687 (direkt/dynamisch unklar); tests/test_server.py:2703 (direkt/dynamisch unklar); tests/test_server.py:2717 (direkt/dynamisch unklar); tests/test_server.py:2724 (direkt/dynamisch unklar); tests/test_server.py:2750 (direkt/dynamisch unklar); tests/test_server.py:2769 (direkt/dynamisch unklar); tests/test_server.py:2779 (direkt/dynamisch unklar); tests/test_server.py:2816 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 9724 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 9735 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 9751 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 9766 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 9776 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 9815 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 9830 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 9838 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 9860 | `planning/` | P4 | offen | tests/test_audit_remediation.py:228 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2708 (direkt/dynamisch unklar); tests/test_server.py:2735 (direkt/dynamisch unklar); tests/test_server.py:2754 (direkt/dynamisch unklar); tests/test_server.py:2759 (direkt/dynamisch unklar); tests/test_server.py:2771 (direkt/dynamisch unklar); tests/test_server.py:2780 (direkt/dynamisch unklar); tests/test_server.py:2783 (direkt/dynamisch unklar); tests/test_server.py:2817 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 9890 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 9914 | `planning/` | P4 | offen | tests/test_server.py:1574 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 9918 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 9926 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 9942 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 9955 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 9960 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 9965 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 9974 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 9983 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 10005 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 10011 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 10015 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 10028 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 10042 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 10048 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 10061 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 10074 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 10095 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 10111 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 10121 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 10137 | `planning/` | P4 | offen | tests/test_server.py:2795 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 10160 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 10176 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 10179 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 10203 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 10212 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:3002 (direkt/dynamisch unklar); tests/test_server.py:3124 (direkt/dynamisch unklar); tests/test_server.py:3145 (direkt/dynamisch unklar); tests/test_server.py:330 (direkt/dynamisch unklar); tests/test_server.py:3598 (direkt/dynamisch unklar); tests/test_server.py:4905 (direkt/dynamisch unklar); tests/test_server.py:4927 (direkt/dynamisch unklar); tests/test_server.py:4983 (direkt/dynamisch unklar); tests/test_server.py:5000 (direkt/dynamisch unklar); tests/test_server.py:5018 (direkt/dynamisch unklar); tests/test_server.py:5036 (direkt/dynamisch unklar); tests/test_server.py:5057 (direkt/dynamisch unklar); tests/test_server.py:5080 (direkt/dynamisch unklar); tests/test_server.py:5125 (direkt/dynamisch unklar); tests/test_server.py:5147 (direkt/dynamisch unklar); tests/test_server.py:5170 (direkt/dynamisch unklar); tests/test_server.py:5186 (direkt/dynamisch unklar); tests/test_server.py:5203 (direkt/dynamisch unklar); tests/test_server.py:5266 (direkt/dynamisch unklar); tests/test_server.py:5328 (direkt/dynamisch unklar); tests/test_server.py:5337 (direkt/dynamisch unklar); tests/test_server.py:5495 (direkt/dynamisch unklar); tests/test_server.py:5526 (direkt/dynamisch unklar); tests/test_server.py:5689 (direkt/dynamisch unklar); tests/test_server.py:5719 (direkt/dynamisch unklar); tests/test_server.py:5737 (direkt/dynamisch unklar); tests/test_server.py:5742 (direkt/dynamisch unklar); tests/test_server.py:5751 (direkt/dynamisch unklar); tests/test_server.py:5755 (direkt/dynamisch unklar); tests/test_server.py:5760 (direkt/dynamisch unklar); tests/test_server.py:5769 (direkt/dynamisch unklar); tests/test_server.py:5788 (direkt/dynamisch unklar); tests/test_server.py:5791 (direkt/dynamisch unklar); tests/test_server.py:5817 (direkt/dynamisch unklar); tests/test_server.py:660 (direkt/dynamisch unklar); tests/test_server.py:683 (direkt/dynamisch unklar); tests/test_server.py:700 (direkt/dynamisch unklar); tests/test_server.py:726 (direkt/dynamisch unklar); tests/test_server.py:730 (direkt/dynamisch unklar); tests/test_server.py:7330 (direkt/dynamisch unklar); tests/test_server.py:833 (direkt/dynamisch unklar); tests/test_server.py:853 (direkt/dynamisch unklar); tests/test_server.py:857 (direkt/dynamisch unklar); tests/test_server.py:880 (direkt/dynamisch unklar); tests/test_server.py:928 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 10230 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2711 (direkt/dynamisch unklar); tests/test_server.py:2712 (direkt/dynamisch unklar); tests/test_server.py:2720 (direkt/dynamisch unklar); tests/test_server.py:2785 (direkt/dynamisch unklar); tests/test_server.py:3056 (direkt/dynamisch unklar); tests/test_server.py:3066 (direkt/dynamisch unklar); tests/test_server.py:3069 (direkt/dynamisch unklar); tests/test_server.py:3080 (direkt/dynamisch unklar); tests/test_server.py:3096 (direkt/dynamisch unklar); tests/test_server.py:3167 (direkt/dynamisch unklar); tests/test_server.py:3908 (direkt/dynamisch unklar); tests/test_server.py:3912 (direkt/dynamisch unklar); tests/test_server.py:3920 (direkt/dynamisch unklar); tests/test_server.py:3924 (direkt/dynamisch unklar); tests/test_server.py:4918 (direkt/dynamisch unklar); tests/test_server.py:4944 (direkt/dynamisch unklar); tests/test_server.py:4961 (direkt/dynamisch unklar); tests/test_server.py:4995 (direkt/dynamisch unklar); tests/test_server.py:5013 (direkt/dynamisch unklar); tests/test_server.py:5031 (direkt/dynamisch unklar); tests/test_server.py:5070 (direkt/dynamisch unklar); tests/test_server.py:5094 (direkt/dynamisch unklar); tests/test_server.py:5116 (direkt/dynamisch unklar); tests/test_server.py:5183 (direkt/dynamisch unklar); tests/test_server.py:5199 (direkt/dynamisch unklar); tests/test_server.py:5220 (direkt/dynamisch unklar); tests/test_server.py:5520 (direkt/dynamisch unklar); tests/test_server.py:5521 (direkt/dynamisch unklar); tests/test_server.py:5610 (direkt/dynamisch unklar); tests/test_server.py:5684 (direkt/dynamisch unklar); tests/test_server.py:5812 (direkt/dynamisch unklar); tests/test_server.py:5842 (direkt/dynamisch unklar); tests/test_server.py:6212 (direkt/dynamisch unklar); tests/test_server.py:723 (direkt/dynamisch unklar); tests/test_server.py:751 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 10242 | `planning/` | P4 | offen | tests/test_server.py:3668 (direkt/dynamisch unklar); tests/test_server.py:3879 (direkt/dynamisch unklar); tests/test_server.py:3941 (direkt/dynamisch unklar); tests/test_server.py:6241 (direkt/dynamisch unklar); tests/test_server.py:6278 (direkt/dynamisch unklar); tests/test_server.py:6322 (direkt/dynamisch unklar); tests/test_server.py:6481 (direkt/dynamisch unklar); tests/test_server.py:8652 (direkt/dynamisch unklar); tests/test_server.py:8742 (direkt/dynamisch unklar); tests/test_server.py:8743 (direkt/dynamisch unklar); tests/test_server.py:951 (direkt/dynamisch unklar); tests/test_server.py:954 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 10270 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3867 (direkt/dynamisch unklar); tests/test_server.py:493 (direkt/dynamisch unklar); tests/test_server.py:687 (direkt/dynamisch unklar); tests/test_server.py:905 (direkt/dynamisch unklar); tests/test_server.py:925 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 10293 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 10308 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 10325 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 10340 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 10363 | `planning/` | P4 | offen | tests/test_server.py:1386 (direkt/dynamisch unklar); tests/test_server.py:1703 (direkt/dynamisch unklar); tests/test_server.py:3653 (direkt/dynamisch unklar); tests/test_server.py:3659 (direkt/dynamisch unklar); tests/test_server.py:3683 (direkt/dynamisch unklar); tests/test_server.py:4292 (direkt/dynamisch unklar); tests/test_server.py:4308 (direkt/dynamisch unklar); tests/test_server.py:4326 (direkt/dynamisch unklar); tests/test_server.py:4341 (direkt/dynamisch unklar); tests/test_server.py:6295 (direkt/dynamisch unklar); tests/test_server.py:6495 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 10388 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3664 (direkt/dynamisch unklar); tests/test_server.py:3673 (direkt/dynamisch unklar); tests/test_server.py:3675 (direkt/dynamisch unklar); tests/test_server.py:3676 (direkt/dynamisch unklar); tests/test_server.py:3678 (direkt/dynamisch unklar); tests/test_server.py:3680 (direkt/dynamisch unklar); tests/test_server.py:3888 (direkt/dynamisch unklar); tests/test_server.py:3951 (direkt/dynamisch unklar); tests/test_server.py:4296 (direkt/dynamisch unklar); tests/test_server.py:4304 (direkt/dynamisch unklar); tests/test_server.py:4312 (direkt/dynamisch unklar); tests/test_server.py:4322 (direkt/dynamisch unklar); tests/test_server.py:4330 (direkt/dynamisch unklar); tests/test_server.py:4338 (direkt/dynamisch unklar); tests/test_server.py:4345 (direkt/dynamisch unklar); tests/test_server.py:6170 (direkt/dynamisch unklar); tests/test_server.py:6259 (direkt/dynamisch unklar); tests/test_server.py:6312 (direkt/dynamisch unklar); tests/test_server.py:6547 (direkt/dynamisch unklar); tests/test_server.py:8658 (direkt/dynamisch unklar); tests/test_server.py:921 (direkt/dynamisch unklar); tests/test_server.py:922 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 10395 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 10412 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 10413 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 10414 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 10415 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 10418 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 10425 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 10430 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 10440 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 10447 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1682 (direkt/dynamisch unklar); tests/test_server.py:1683 (direkt/dynamisch unklar); tests/test_server.py:1684 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 10474 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_audit_remediation.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1692 (direkt/dynamisch unklar); tests/test_server.py:1693 (direkt/dynamisch unklar); tests/test_server.py:1698 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 10506 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1707 (direkt/dynamisch unklar); tests/test_server.py:1708 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 10534 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1858 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 10555 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 10575 | `activities/` | P3 | offen | tests/test_server.py:489 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 10616 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 10621 | `planning/` | P4 | offen | tests/test_server.py:2694 (direkt/dynamisch unklar); tests/test_server.py:2707 (direkt/dynamisch unklar); tests/test_server.py:2710 (direkt/dynamisch unklar); tests/test_server.py:2758 (direkt/dynamisch unklar); tests/test_server.py:2784 (direkt/dynamisch unklar); tests/test_server.py:2818 (direkt/dynamisch unklar); tests/test_server.py:2821 (direkt/dynamisch unklar); tests/test_server.py:2981 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3031 (direkt/dynamisch unklar); tests/test_server.py:3048 (direkt/dynamisch unklar); tests/test_server.py:3142 (direkt/dynamisch unklar); tests/test_server.py:3787 (direkt/dynamisch unklar); tests/test_server.py:3876 (direkt/dynamisch unklar); tests/test_server.py:3934 (direkt/dynamisch unklar); tests/test_server.py:4305 (direkt/dynamisch unklar); tests/test_server.py:4323 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 10626 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 10633 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 10644 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 10656 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 10681 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 10697 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 10705 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 10719 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 10731 | `planning/` | P4 | offen | tests/test_server.py:3016 (direkt/dynamisch unklar); tests/test_server.py:3031 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 10750 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 10755 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 10772 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 10786 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 10793 | `calendar/` | P3 | offen | tests/test_server.py:3116 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 10808 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 10821 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 10834 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 10891 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 10908 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 10948 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 10955 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 10963 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 10971 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 10984 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 10994 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 11006 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 11035 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 11045 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 11067 | `planning/` | P4 | offen | tests/test_server.py:266 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 11084 | `sync/` | P6 | offen | tests/test_server.py:3907 (direkt/dynamisch unklar); tests/test_server.py:3911 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 11089 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 11107 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 11114 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 11123 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 11138 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 11143 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 11149 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 11157 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 11169 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 11178 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 11195 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 11215 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 11218 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 11231 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 11243 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 11266 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 11286 | `planning/` | P4 | offen | tests/test_server.py:6065 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6094 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6107 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6127 (direkt/dynamisch unklar); tests/test_server.py:616 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6206 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6230 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6271 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6289 (direkt/dynamisch unklar); tests/test_server.py:629 (Monkeypatch/getattr/sys.modules) |
| Funktion | `plan_library_workout_remote` | 11327 | `planning/` | P4 | offen | tests/test_server.py:6470 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 11331 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 11352 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 11367 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 11373 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 11380 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 11395 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 11410 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 11420 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 11426 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 11441 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 11449 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1390 (direkt/dynamisch unklar); tests/test_server.py:3671 (direkt/dynamisch unklar); tests/test_server.py:3674 (direkt/dynamisch unklar); tests/test_server.py:3677 (direkt/dynamisch unklar); tests/test_server.py:3679 (direkt/dynamisch unklar); tests/test_server.py:3685 (direkt/dynamisch unklar); tests/test_server.py:3687 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 11473 | `planning/` | P4 | offen | tests/test_server.py:6485 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 11492 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 11508 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 11520 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 11534 | `calendar/` | P3 | offen | tests/test_server.py:7947 (direkt/dynamisch unklar); tests/test_server.py:7957 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 11569 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 11599 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 11617 | `sync/` | P6 | offen | tests/test_server.py:1859 (direkt/dynamisch unklar); tests/test_server.py:2104 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 11621 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 11636 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 11655 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 11668 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 11682 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 11701 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 11714 | `sync/` | P6 | offen | tests/test_server.py:3886 (direkt/dynamisch unklar); tests/test_server.py:3892 (direkt/dynamisch unklar); tests/test_server.py:3948 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 11729 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 11737 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 11761 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 11766 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 11789 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 11796 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 11821 | `planning/` | P4 | offen | tests/test_server.py:4298 (direkt/dynamisch unklar); tests/test_server.py:4318 (direkt/dynamisch unklar); tests/test_server.py:4333 (direkt/dynamisch unklar); tests/test_server.py:4347 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 11835 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 11844 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 11855 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 11864 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 11876 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 11889 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 11893 | `sync/` | P6 | offen | tests/test_server.py:6534 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8750 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 11906 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 11919 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 11923 | `sync/` | P6 | offen | tests/test_server.py:267 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 11942 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 11957 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 11972 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 11988 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 12001 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 12018 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 12029 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 12045 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 12063 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 12082 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 12105 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 12120 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 12129 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 12150 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 12168 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 12192 | `planning/` | P4 | offen | tests/test_server.py:2752 (direkt/dynamisch unklar); tests/test_server.py:2770 (direkt/dynamisch unklar); tests/test_server.py:3053 (direkt/dynamisch unklar); tests/test_server.py:3067 (direkt/dynamisch unklar); tests/test_server.py:3097 (direkt/dynamisch unklar); tests/test_server.py:3129 (direkt/dynamisch unklar); tests/test_server.py:3136 (direkt/dynamisch unklar); tests/test_server.py:3138 (direkt/dynamisch unklar); tests/test_server.py:3140 (direkt/dynamisch unklar); tests/test_server.py:3150 (direkt/dynamisch unklar); tests/test_server.py:3152 (direkt/dynamisch unklar); tests/test_server.py:3601 (direkt/dynamisch unklar); tests/test_server.py:3875 (direkt/dynamisch unklar); tests/test_server.py:3923 (direkt/dynamisch unklar); tests/test_server.py:5041 (direkt/dynamisch unklar); tests/test_server.py:5741 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 12218 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 12229 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 12240 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 12250 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 12256 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 12267 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 12279 | `planning/` | P4 | offen | tests/test_server.py:3099 (direkt/dynamisch unklar); tests/test_server.py:3102 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 12297 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:92 (direkt/dynamisch unklar); tests/test_server.py:1650 (direkt/dynamisch unklar); tests/test_server.py:1651 (direkt/dynamisch unklar); tests/test_server.py:2980 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5420 (direkt/dynamisch unklar); tests/test_server.py:5422 (direkt/dynamisch unklar); tests/test_server.py:6539 (direkt/dynamisch unklar); tests/test_server.py:6562 (direkt/dynamisch unklar); tests/test_server.py:7719 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 12302 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:110 (direkt/dynamisch unklar); tests/test_provider_review.py:230 (direkt/dynamisch unklar); tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_provider_review.py:63 (direkt/dynamisch unklar); tests/test_provider_review.py:87 (direkt/dynamisch unklar); tests/test_server.py:1418 (direkt/dynamisch unklar); tests/test_server.py:1630 (direkt/dynamisch unklar); tests/test_server.py:1667 (direkt/dynamisch unklar); tests/test_server.py:1675 (direkt/dynamisch unklar); tests/test_server.py:1715 (direkt/dynamisch unklar); tests/test_server.py:2323 (direkt/dynamisch unklar); tests/test_server.py:2348 (direkt/dynamisch unklar); tests/test_server.py:3627 (direkt/dynamisch unklar); tests/test_server.py:3692 (direkt/dynamisch unklar); tests/test_server.py:4314 (direkt/dynamisch unklar); tests/test_server.py:444 (direkt/dynamisch unklar); tests/test_server.py:5374 (direkt/dynamisch unklar); tests/test_server.py:5415 (direkt/dynamisch unklar); tests/test_server.py:6551 (direkt/dynamisch unklar); tests/test_server.py:7332 (direkt/dynamisch unklar); tests/test_server.py:7710 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 12312 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 12338 | `sync/` | P6 | offen | tests/test_server.py:1003 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 12363 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 12368 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 12378 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 12386 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 12417 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 12439 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 12450 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 12464 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 12486 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 12503 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 12537 | `planning/` | P4 | offen | tests/test_server.py:3044 (direkt/dynamisch unklar); tests/test_server.py:3046 (direkt/dynamisch unklar); tests/test_server.py:3054 (direkt/dynamisch unklar); tests/test_server.py:3065 (direkt/dynamisch unklar); tests/test_server.py:3068 (direkt/dynamisch unklar); tests/test_server.py:3076 (direkt/dynamisch unklar); tests/test_server.py:3095 (direkt/dynamisch unklar); tests/test_server.py:3098 (direkt/dynamisch unklar); tests/test_server.py:3101 (direkt/dynamisch unklar); tests/test_server.py:3585 (direkt/dynamisch unklar); tests/test_server.py:3590 (direkt/dynamisch unklar); tests/test_server.py:5669 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 12585 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 12601 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 12613 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 12625 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 12630 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 12640 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 12647 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 12654 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 12665 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 12680 | `sync/` | P6 | offen | tests/test_server.py:6397 (direkt/dynamisch unklar); tests/test_server.py:6535 (direkt/dynamisch unklar); tests/test_server.py:6561 (direkt/dynamisch unklar); tests/test_server.py:6571 (direkt/dynamisch unklar); tests/test_server.py:6647 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 12715 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 12730 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 12759 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 12788 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 12808 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 12825 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 12882 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 12897 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 12908 | `sync/` | P6 | offen | tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:574 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6066 (direkt/dynamisch unklar); tests/test_server.py:6081 (direkt/dynamisch unklar); tests/test_server.py:6096 (direkt/dynamisch unklar); tests/test_server.py:6109 (direkt/dynamisch unklar); tests/test_server.py:6138 (direkt/dynamisch unklar); tests/test_server.py:6167 (direkt/dynamisch unklar); tests/test_server.py:619 (direkt/dynamisch unklar); tests/test_server.py:6207 (direkt/dynamisch unklar); tests/test_server.py:6208 (direkt/dynamisch unklar); tests/test_server.py:6232 (direkt/dynamisch unklar); tests/test_server.py:6234 (direkt/dynamisch unklar); tests/test_server.py:6254 (direkt/dynamisch unklar); tests/test_server.py:6272 (direkt/dynamisch unklar); tests/test_server.py:632 (direkt/dynamisch unklar); tests/test_server.py:6389 (direkt/dynamisch unklar); tests/test_server.py:6490 (direkt/dynamisch unklar); tests/test_server.py:7763 (direkt/dynamisch unklar); tests/test_server.py:8030 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 12942 | `performance/` | P3 | offen | tests/test_provider_review.py:77 (direkt/dynamisch unklar); tests/test_server.py:550 (Monkeypatch/getattr/sys.modules); tests/test_server.py:563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7324 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 12966 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 12973 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 12980 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 12998 | `activities/` | P3 | offen | tests/test_server.py:5288 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 13010 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 13027 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 13040 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 13057 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 13078 | `performance/` | P3 | offen | tests/test_server.py:7221 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 13087 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 13099 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 13115 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 13130 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 13166 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 13176 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 13190 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 13206 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 13223 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 13233 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 13244 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 13258 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 13270 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 13275 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 13307 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 13316 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 13322 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 13329 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 13343 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 13356 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 13360 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 13389 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 13396 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 13433 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 13453 | `performance/` | P3 | offen | tests/test_server.py:3346 (direkt/dynamisch unklar); tests/test_server.py:3355 (direkt/dynamisch unklar); tests/test_server.py:3463 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 13482 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 13496 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 13512 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 13520 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 13530 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 13557 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 13572 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 13595 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 13613 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 13645 | `activities/` | P3 | offen | tests/test_server.py:7120 (direkt/dynamisch unklar); tests/test_server.py:7142 (direkt/dynamisch unklar); tests/test_server.py:7148 (direkt/dynamisch unklar); tests/test_server.py:7157 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 13690 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 13723 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 13744 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 13756 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 13776 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 13789 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 13820 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 13850 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 13861 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 13904 | `performance/` | P3 | offen | tests/test_provider_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:3486 (direkt/dynamisch unklar); tests/test_server.py:3516 (direkt/dynamisch unklar); tests/test_server.py:3545 (direkt/dynamisch unklar); tests/test_server.py:3566 (direkt/dynamisch unklar); tests/test_server.py:3578 (direkt/dynamisch unklar); tests/test_server.py:7059 (direkt/dynamisch unklar); tests/test_server.py:7081 (direkt/dynamisch unklar); tests/test_server.py:7108 (direkt/dynamisch unklar); tests/test_server.py:7177 (direkt/dynamisch unklar); tests/test_server.py:7191 (direkt/dynamisch unklar); tests/test_server.py:7207 (direkt/dynamisch unklar); tests/test_server.py:7238 (direkt/dynamisch unklar); tests/test_server.py:7259 (direkt/dynamisch unklar); tests/test_server.py:7281 (direkt/dynamisch unklar); tests/test_server.py:7301 (direkt/dynamisch unklar); tests/test_server.py:7307 (direkt/dynamisch unklar); tests/test_server.py:7311 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 13975 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 13989 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 13993 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 13997 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 14002 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 14006 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 14010 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 14014 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 14018 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 14037 | `coach/context.py` | P7 | offen | tests/test_server.py:5278 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 14056 | `coach/context.py` | P7 | offen | tests/test_server.py:5270 (direkt/dynamisch unklar); tests/test_server.py:5307 (direkt/dynamisch unklar); tests/test_server.py:5308 (direkt/dynamisch unklar); tests/test_server.py:5329 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 14102 | `coach/context.py` | P7 | offen | tests/test_server.py:1537 (direkt/dynamisch unklar); tests/test_server.py:1611 (direkt/dynamisch unklar); tests/test_server.py:2337 (direkt/dynamisch unklar); tests/test_server.py:3299 (direkt/dynamisch unklar); tests/test_server.py:5350 (direkt/dynamisch unklar); tests/test_server.py:5356 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6732 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 14167 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 14185 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 14195 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 14212 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:248 (direkt/dynamisch unklar); tests/test_provider_review.py:282 (direkt/dynamisch unklar); tests/test_server.py:3665 (direkt/dynamisch unklar); tests/test_server.py:5346 (direkt/dynamisch unklar); tests/test_server.py:5357 (direkt/dynamisch unklar); tests/test_server.py:5358 (direkt/dynamisch unklar); tests/test_server.py:5375 (direkt/dynamisch unklar); tests/test_server.py:5386 (direkt/dynamisch unklar); tests/test_server.py:5418 (direkt/dynamisch unklar); tests/test_server.py:6710 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 14252 | `coach/context.py` | P7 | offen | tests/test_server.py:5240 (direkt/dynamisch unklar); tests/test_server.py:5380 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 14308 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 14338 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_openai_usage_summary_unlocked` | 14348 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_usage_summary` | 14371 | `providers/` | P2 | offen | tests/test_server.py:8094 (direkt/dynamisch unklar); tests/test_server.py:8124 (direkt/dynamisch unklar); tests/test_server.py:8316 (direkt/dynamisch unklar); tests/test_server.py:8326 (direkt/dynamisch unklar); tests/test_server.py:8350 (direkt/dynamisch unklar); tests/test_server.py:8373 (direkt/dynamisch unklar); tests/test_server.py:8517 (direkt/dynamisch unklar); tests/test_server.py:8555 (direkt/dynamisch unklar) |
| Funktion | `_record_openai_usage_unlocked` | 14379 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_usage` | 14408 | `providers/` | P2 | offen | tests/test_server.py:5860 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8512 (direkt/dynamisch unklar); tests/test_server.py:8553 (direkt/dynamisch unklar) |
| Funktion | `_validate_openai_response` | 14415 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8494 (direkt/dynamisch unklar); tests/test_server.py:8497 (direkt/dynamisch unklar); tests/test_server.py:8500 (direkt/dynamisch unklar) |
| Funktion | `openai_endpoint` | 14437 | `providers/` | P2 | offen | tests/test_server.py:4816 (direkt/dynamisch unklar); tests/test_server.py:4817 (direkt/dynamisch unklar); tests/test_server.py:4819 (direkt/dynamisch unklar); tests/test_server.py:4828 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 14454 | `providers/` | P2 | offen | tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4840 (direkt/dynamisch unklar); tests/test_server.py:5463 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5472 (direkt/dynamisch unklar); tests/test_server.py:6065 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8195 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8507 (direkt/dynamisch unklar) |
| Funktion | `multipart_form_data` | 14478 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VOICE_AUDIO_TYPES` | 14503 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `normalized_audio_type` | 14515 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `transcribe_audio` | 14519 | `providers/` | P2 | offen | tests/test_server.py:4579 (direkt/dynamisch unklar); tests/test_server.py:4799 (direkt/dynamisch unklar); tests/test_server.py:4872 (direkt/dynamisch unklar); tests/test_server.py:4874 (direkt/dynamisch unklar) |
| Funktion | `_provider_usage_summary` | 14571 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_usage_summary` | 14588 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_status` | 14593 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_usage` | 14599 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_content_has_function_response` | 14618 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 14623 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 14630 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 14641 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 14657 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 14669 | `providers/` | P2 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4502 (direkt/dynamisch unklar); tests/test_server.py:4634 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 14677 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 14689 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 14705 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 14721 | `providers/` | P2 | offen | tests/test_server.py:4513 (direkt/dynamisch unklar); tests/test_server.py:4518 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 14743 | `providers/` | P2 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_text` | 14765 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_tools` | 14769 | `providers/` | P2 | offen | tests/test_server.py:4674 (direkt/dynamisch unklar) |
| Funktion | `_gemini_request_payload` | 14773 | `providers/` | P2 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4530 (direkt/dynamisch unklar); tests/test_server.py:4543 (direkt/dynamisch unklar); tests/test_server.py:4613 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 14869 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 14888 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 14927 | `providers/` | P2 | offen | tests/test_server.py:4371 (direkt/dynamisch unklar); tests/test_server.py:4373 (direkt/dynamisch unklar); tests/test_server.py:4440 (direkt/dynamisch unklar); tests/test_server.py:4443 (direkt/dynamisch unklar); tests/test_server.py:4565 (direkt/dynamisch unklar); tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 14934 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `request_ai_provider` | 15075 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 15080 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4610 (direkt/dynamisch unklar); tests/test_server.py:5464 (direkt/dynamisch unklar); tests/test_server.py:5855 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8196 (direkt/dynamisch unklar) |
| Funktion | `_openai_response_id` | 15105 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `retrieve_openai_response` | 15112 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 15127 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 15145 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5861 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 15182 | `coach/context.py` | P7 | offen | tests/test_server.py:6121 (direkt/dynamisch unklar) |
| Funktion | `_notify_openai_stream_response_id` | 15187 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_forward_openai_stream_delta` | 15200 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_stream_final_response` | 15208 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_consume_openai_sse_event` | 15215 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_read_openai_stream_response` | 15234 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_openai_stream_failure` | 15270 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_capture_openai_stream_failure` | 15288 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 15302 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 15314 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 15325 | `providers/` | P2 | offen | tests/test_server.py:8176 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 15342 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 15358 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 15373 | `providers/` | P2 | offen | tests/test_server.py:4864 (direkt/dynamisch unklar); tests/test_server.py:8268 (direkt/dynamisch unklar); tests/test_server.py:8309 (direkt/dynamisch unklar); tests/test_server.py:8323 (direkt/dynamisch unklar); tests/test_server.py:8347 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8378 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 15450 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4415 (direkt/dynamisch unklar); tests/test_server.py:5961 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8379 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 15476 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 15495 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 15508 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 15526 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 15539 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 15545 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 15553 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:292 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4643 (direkt/dynamisch unklar); tests/test_server.py:5486 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 15562 | `providers/` | P2 | offen | tests/test_server.py:4355 (direkt/dynamisch unklar); tests/test_server.py:4387 (direkt/dynamisch unklar); tests/test_server.py:4421 (direkt/dynamisch unklar); tests/test_server.py:4609 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 15566 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 15567 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 15570 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 15574 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 15587 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 15612 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 15636 | `activities/` | P3 | offen | tests/test_server.py:7713 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 15656 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8616 (direkt/dynamisch unklar); tests/test_server.py:8627 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 15678 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 15687 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 15709 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8643 (direkt/dynamisch unklar); tests/test_server.py:8655 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 15733 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 15742 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8644 (direkt/dynamisch unklar); tests/test_server.py:8656 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 15771 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 15775 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5986 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 15792 | `coach/proposals.py` | P7 | offen | tests/test_server.py:6015 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 15796 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:6006 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 15808 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 15825 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 15852 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 15861 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 15878 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 15930 | `sync/` | P6 | offen | tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4623 (direkt/dynamisch unklar); tests/test_server.py:5872 (direkt/dynamisch unklar); tests/test_server.py:5900 (direkt/dynamisch unklar); tests/test_server.py:5921 (direkt/dynamisch unklar); tests/test_server.py:5948 (direkt/dynamisch unklar); tests/test_server.py:5975 (direkt/dynamisch unklar); tests/test_server.py:5999 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 15963 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5919 (direkt/dynamisch unklar); tests/test_server.py:8387 (direkt/dynamisch unklar); tests/test_server.py:8390 (direkt/dynamisch unklar); tests/test_server.py:8404 (direkt/dynamisch unklar); tests/test_server.py:8425 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8452 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8465 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 15977 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 15992 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5935 (direkt/dynamisch unklar); tests/test_server.py:8427 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8454 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 16001 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 16010 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 16022 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 16039 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:257 (direkt/dynamisch unklar); tests/test_server.py:8393 (direkt/dynamisch unklar); tests/test_server.py:8395 (direkt/dynamisch unklar); tests/test_server.py:8469 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 16047 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5943 (direkt/dynamisch unklar); tests/test_server.py:8399 (direkt/dynamisch unklar); tests/test_server.py:8410 (direkt/dynamisch unklar); tests/test_server.py:8426 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8474 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 16054 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 16055 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 16056 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 16056 | `coach/` | P7 | offen | tests/test_server.py:354 (direkt/dynamisch unklar); tests/test_server.py:410 (direkt/dynamisch unklar); tests/test_server.py:4880 (direkt/dynamisch unklar); tests/test_server.py:4883 (direkt/dynamisch unklar); tests/test_server.py:5233 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 16056 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 16056 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 16065 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 16073 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 16077 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 16082 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 16093 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 16118 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 16137 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 16149 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:3045 (direkt/dynamisch unklar); tests/test_server.py:3047 (direkt/dynamisch unklar); tests/test_server.py:5499 (direkt/dynamisch unklar); tests/test_server.py:5535 (direkt/dynamisch unklar); tests/test_server.py:5558 (direkt/dynamisch unklar); tests/test_server.py:5560 (direkt/dynamisch unklar); tests/test_server.py:5576 (direkt/dynamisch unklar); tests/test_server.py:5583 (direkt/dynamisch unklar); tests/test_server.py:5597 (direkt/dynamisch unklar); tests/test_server.py:5620 (direkt/dynamisch unklar); tests/test_server.py:5645 (direkt/dynamisch unklar); tests/test_server.py:5674 (direkt/dynamisch unklar); tests/test_server.py:5694 (direkt/dynamisch unklar); tests/test_server.py:5746 (direkt/dynamisch unklar); tests/test_server.py:5759 (direkt/dynamisch unklar); tests/test_server.py:5765 (direkt/dynamisch unklar); tests/test_server.py:5794 (direkt/dynamisch unklar); tests/test_server.py:5821 (direkt/dynamisch unklar); tests/test_server.py:5824 (direkt/dynamisch unklar); tests/test_server.py:5845 (direkt/dynamisch unklar); tests/test_server.py:691 (direkt/dynamisch unklar); tests/test_server.py:704 (direkt/dynamisch unklar); tests/test_server.py:780 (direkt/dynamisch unklar); tests/test_server.py:815 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 16172 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 16179 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 16186 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 16204 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 16214 | `coach/proposals.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:277 (direkt/dynamisch unklar); tests/test_server.py:302 (direkt/dynamisch unklar); tests/test_server.py:4549 (direkt/dynamisch unklar); tests/test_server.py:5480 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 16227 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 16236 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 16247 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 16279 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 16305 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 16325 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 16349 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 16361 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 16374 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 16388 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 16396 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 16407 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 16429 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 16439 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 16453 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 16465 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 16479 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 16487 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 16500 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 16509 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 16531 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 16549 | `planning/` | P4 | offen | tests/test_server.py:4910 (direkt/dynamisch unklar); tests/test_server.py:4932 (direkt/dynamisch unklar); tests/test_server.py:4951 (direkt/dynamisch unklar); tests/test_server.py:4973 (direkt/dynamisch unklar); tests/test_server.py:4988 (direkt/dynamisch unklar); tests/test_server.py:5004 (direkt/dynamisch unklar); tests/test_server.py:5022 (direkt/dynamisch unklar); tests/test_server.py:5044 (direkt/dynamisch unklar); tests/test_server.py:5062 (direkt/dynamisch unklar); tests/test_server.py:5085 (direkt/dynamisch unklar); tests/test_server.py:5129 (direkt/dynamisch unklar); tests/test_server.py:5154 (direkt/dynamisch unklar); tests/test_server.py:5175 (direkt/dynamisch unklar); tests/test_server.py:5190 (direkt/dynamisch unklar); tests/test_server.py:5209 (direkt/dynamisch unklar); tests/test_server.py:5226 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 16560 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 16570 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 16587 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 16598 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 16628 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 16646 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 16652 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 16665 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 16683 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 16699 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 16712 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 16726 | `planning/` | P4 | offen | tests/test_server.py:5600 (direkt/dynamisch unklar); tests/test_server.py:5647 (direkt/dynamisch unklar); tests/test_server.py:5675 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 16760 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:335 (direkt/dynamisch unklar); tests/test_server.py:366 (direkt/dynamisch unklar); tests/test_server.py:8749 (direkt/dynamisch unklar); tests/test_server.py:884 (direkt/dynamisch unklar); tests/test_server.py:962 (direkt/dynamisch unklar); tests/test_server.py:971 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 16773 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 16785 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 16800 | `planning/` | P4 | offen | tests/test_server.py:375 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 16812 | `planning/` | P4 | offen | tests/test_server.py:645 (direkt/dynamisch unklar); tests/test_server.py:655 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 16842 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 16850 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 16857 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 16879 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 16886 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 16892 | `coach/proposals.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 16910 | `planning/` | P4 | offen | tests/test_server.py:399 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 16938 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 16947 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 16974 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 17000 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 17005 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 17011 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 17025 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 17032 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 17040 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 17047 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 17056 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 17063 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 17076 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 17099 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 17113 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 17127 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 17155 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 17171 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 17190 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 17210 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 17232 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 17248 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 17265 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 17300 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 17312 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 17327 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 17347 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 17373 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 17391 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 17399 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 17420 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 17447 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 17471 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 17498 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 17519 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:289 (direkt/dynamisch unklar); tests/test_server.py:321 (direkt/dynamisch unklar); tests/test_server.py:345 (direkt/dynamisch unklar); tests/test_server.py:378 (direkt/dynamisch unklar); tests/test_server.py:400 (direkt/dynamisch unklar); tests/test_server.py:425 (direkt/dynamisch unklar); tests/test_server.py:432 (direkt/dynamisch unklar); tests/test_server.py:472 (direkt/dynamisch unklar); tests/test_server.py:501 (direkt/dynamisch unklar); tests/test_server.py:507 (direkt/dynamisch unklar); tests/test_server.py:5108 (direkt/dynamisch unklar); tests/test_server.py:511 (direkt/dynamisch unklar); tests/test_server.py:528 (direkt/dynamisch unklar); tests/test_server.py:532 (direkt/dynamisch unklar); tests/test_server.py:5505 (direkt/dynamisch unklar); tests/test_server.py:5541 (direkt/dynamisch unklar); tests/test_server.py:5626 (direkt/dynamisch unklar); tests/test_server.py:5700 (direkt/dynamisch unklar); tests/test_server.py:5724 (direkt/dynamisch unklar); tests/test_server.py:5729 (direkt/dynamisch unklar); tests/test_server.py:5778 (direkt/dynamisch unklar); tests/test_server.py:5800 (direkt/dynamisch unklar); tests/test_server.py:669 (direkt/dynamisch unklar); tests/test_server.py:711 (direkt/dynamisch unklar); tests/test_server.py:740 (direkt/dynamisch unklar); tests/test_server.py:759 (direkt/dynamisch unklar); tests/test_server.py:788 (direkt/dynamisch unklar); tests/test_server.py:821 (direkt/dynamisch unklar); tests/test_server.py:841 (direkt/dynamisch unklar); tests/test_server.py:868 (direkt/dynamisch unklar); tests/test_server.py:894 (direkt/dynamisch unklar); tests/test_server.py:913 (direkt/dynamisch unklar); tests/test_server.py:939 (direkt/dynamisch unklar); tests/test_server.py:964 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 17561 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 17565 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 17578 | `coach/authorization.py` | P7 | offen | tests/test_server.py:8763 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 17590 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 17609 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 17625 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 17636 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 17658 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 17673 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 17691 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 17721 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 17727 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 17741 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 17751 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 17764 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 17777 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 17794 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 17807 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5838 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 17834 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 17851 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 17856 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 17865 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 17879 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 17892 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 17902 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 17915 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 17936 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 17959 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 17970 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 17979 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 17991 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 18005 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 18013 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 18028 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 18048 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 18072 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 18086 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 18097 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 18122 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 18138 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 18153 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 18210 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 18238 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 18268 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 18284 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 18304 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 18318 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 18330 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 18340 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 18391 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 18453 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 18457 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 18462 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 18480 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 18499 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 18509 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 18535 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 18573 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 18599 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 18624 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 18655 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 18695 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 18725 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 18745 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 18803 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 18807 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 18823 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 18839 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 18871 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 18915 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 18931 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 18950 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 18976 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 19053 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 19058 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 19067 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 19072 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 19099 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 19117 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 19146 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 19165 | `coach/service.py` | P7 | offen | tests/test_server.py:4451 (direkt/dynamisch unklar); tests/test_server.py:4466 (direkt/dynamisch unklar); tests/test_server.py:4480 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 19175 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 19190 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 19222 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 19237 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4553 (direkt/dynamisch unklar); tests/test_server.py:5491 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 19250 | `coach/authorization.py` | P7 | offen | tests/test_server.py:5879 (direkt/dynamisch unklar); tests/test_server.py:5882 (direkt/dynamisch unklar); tests/test_server.py:8403 (direkt/dynamisch unklar); tests/test_server.py:8406 (direkt/dynamisch unklar); tests/test_server.py:8407 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 19269 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 19282 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 19306 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 19322 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 19333 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 19348 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:247 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5908 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5932 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5964 (direkt/dynamisch unklar); tests/test_server.py:6027 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 19372 | `sync/` | P6 | offen | tests/test_server.py:4629 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 19413 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:254 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4628 (direkt/dynamisch unklar); tests/test_server.py:5906 (direkt/dynamisch unklar); tests/test_server.py:5925 (direkt/dynamisch unklar); tests/test_server.py:5952 (direkt/dynamisch unklar); tests/test_server.py:5981 (direkt/dynamisch unklar); tests/test_server.py:6005 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 19438 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 19464 | `coach/authorization.py` | P7 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 19474 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 19478 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 19486 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 19492 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 19502 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 19519 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 19550 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 19572 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 19587 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:148 (direkt/dynamisch unklar); tests/test_server.py:5909 (direkt/dynamisch unklar); tests/test_server.py:5933 (direkt/dynamisch unklar); tests/test_server.py:5987 (direkt/dynamisch unklar); tests/test_server.py:6030 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 19608 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 19623 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `local_now` | 19635 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1157 (direkt/dynamisch unklar); tests/test_server.py:1541 (direkt/dynamisch unklar); tests/test_server.py:1557 (direkt/dynamisch unklar); tests/test_server.py:1558 (direkt/dynamisch unklar); tests/test_server.py:1579 (direkt/dynamisch unklar); tests/test_server.py:1597 (direkt/dynamisch unklar); tests/test_server.py:1616 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1629 (direkt/dynamisch unklar); tests/test_server.py:1666 (direkt/dynamisch unklar); tests/test_server.py:1674 (direkt/dynamisch unklar); tests/test_server.py:1714 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2640 (direkt/dynamisch unklar); tests/test_server.py:2705 (direkt/dynamisch unklar); tests/test_server.py:2715 (direkt/dynamisch unklar); tests/test_server.py:2893 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2953 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2983 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2992 (direkt/dynamisch unklar); tests/test_server.py:3480 (direkt/dynamisch unklar); tests/test_server.py:3499 (direkt/dynamisch unklar); tests/test_server.py:3531 (direkt/dynamisch unklar); tests/test_server.py:3556 (direkt/dynamisch unklar); tests/test_server.py:3646 (direkt/dynamisch unklar); tests/test_server.py:3647 (direkt/dynamisch unklar); tests/test_server.py:3691 (direkt/dynamisch unklar); tests/test_server.py:496 (direkt/dynamisch unklar); tests/test_server.py:5248 (direkt/dynamisch unklar); tests/test_server.py:5297 (direkt/dynamisch unklar); tests/test_server.py:5314 (direkt/dynamisch unklar); tests/test_server.py:5336 (direkt/dynamisch unklar); tests/test_server.py:5363 (direkt/dynamisch unklar); tests/test_server.py:5395 (direkt/dynamisch unklar); tests/test_server.py:6070 (direkt/dynamisch unklar); tests/test_server.py:7404 (direkt/dynamisch unklar); tests/test_server.py:7722 (direkt/dynamisch unklar); tests/test_server.py:8504 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 19644 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1898 (direkt/dynamisch unklar); tests/test_server.py:1899 (direkt/dynamisch unklar); tests/test_server.py:1900 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 19652 | `sync/scheduler.py` | P8 | offen | tests/test_server.py:1897 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 19660 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 19665 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 19676 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 19688 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4160 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 19691 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 19698 | `sync/scheduler.py` | P8 | offen | tests/test_server.py:4158 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 19715 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 19721 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 19729 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 19741 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 19773 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 19794 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 19808 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 19821 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 19840 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 19874 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1724 (direkt/dynamisch unklar); tests/test_server.py:1738 (direkt/dynamisch unklar); tests/test_server.py:1781 (direkt/dynamisch unklar); tests/test_server.py:1863 (direkt/dynamisch unklar); tests/test_server.py:8544 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 19948 | `http_api/` | P10 | offen | tests/test_server.py:1171 (direkt/dynamisch unklar); tests/test_server.py:2985 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 19984 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 19989 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 19993 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:97 (direkt/dynamisch unklar); tests/test_server.py:1221 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 20000 | `http_api/` | P10 | offen | tests/test_server.py:1193 (direkt/dynamisch unklar); tests/test_server.py:1201 (direkt/dynamisch unklar); tests/test_server.py:1624 (direkt/dynamisch unklar); tests/test_server.py:1669 (direkt/dynamisch unklar); tests/test_server.py:2334 (direkt/dynamisch unklar); tests/test_server.py:3696 (direkt/dynamisch unklar); tests/test_server.py:7333 (direkt/dynamisch unklar); tests/test_server.py:8544 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 20112 | `observability.py` | P1 | offen | tests/test_server.py:7867 (direkt/dynamisch unklar); tests/test_server.py:7919 (direkt/dynamisch unklar); tests/test_server.py:8033 (direkt/dynamisch unklar); tests/test_server.py:8064 (direkt/dynamisch unklar); tests/test_server.py:8315 (direkt/dynamisch unklar); tests/test_server.py:8351 (direkt/dynamisch unklar); tests/test_server.py:8600 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS_SECRET_KEYS` | 20129 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_VALUE_KEYS` | 20130 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_KEYS` | 20131 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_submitted_settings` | 20134 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_settings_file` | 20149 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_rewrite_settings_lines` | 20156 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `save_settings` | 20176 | `settings.py` | P1 | offen | tests/test_server.py:6660 (direkt/dynamisch unklar); tests/test_server.py:6676 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 20191 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 20207 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 20228 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 20242 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 20258 | `observability.py` | P1 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 20267 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7782 (direkt/dynamisch unklar); tests/test_server.py:7784 (direkt/dynamisch unklar); tests/test_server.py:7785 (direkt/dynamisch unklar); tests/test_server.py:7832 (direkt/dynamisch unklar); tests/test_server.py:7895 (direkt/dynamisch unklar); tests/test_server.py:7910 (direkt/dynamisch unklar); tests/test_server.py:8717 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 20330 | `backup/` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1404 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 20380 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 20381 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 20405 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 20409 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 20420 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 20424 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 20434 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 20442 | `backup/` | P9 | offen | tests/test_audit_remediation.py:171 (direkt/dynamisch unklar); tests/test_server.py:1419 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 20581 | `db/manager.py` | P1 | offen | tests/test_server.py:6599 (direkt/dynamisch unklar); tests/test_server.py:6612 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 20584 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 20597 | `backup/` | P9 | offen | tests/test_audit_remediation.py:275 (direkt/dynamisch unklar); tests/test_server.py:6588 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 20606 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 20627 | `coach/morning.py` | P8 | offen | tests/test_server.py:1447 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 20638 | `backup/` | P9 | offen | tests/test_audit_remediation.py:277 (direkt/dynamisch unklar); tests/test_server.py:6589 (direkt/dynamisch unklar); tests/test_server.py:6605 (direkt/dynamisch unklar); tests/test_server.py:6618 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 20643 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 20652 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 20669 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 20681 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 20699 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 20706 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 20727 | `coach/morning.py` | P8 | offen | tests/test_server.py:1487 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1503 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4642 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5485 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8663 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 20740 | `coach/morning.py` | P8 | offen | tests/test_server.py:1496 (direkt/dynamisch unklar); tests/test_server.py:1500 (direkt/dynamisch unklar); tests/test_server.py:1506 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 20755 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 20762 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 20769 | `privacy.py` | P9 | offen | tests/test_server.py:1499 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 20784 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:102 (direkt/dynamisch unklar); tests/test_provider_review.py:116 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (direkt/dynamisch unklar); tests/test_provider_review.py:146 (direkt/dynamisch unklar); tests/test_provider_review.py:164 (direkt/dynamisch unklar); tests/test_server.py:1488 (direkt/dynamisch unklar); tests/test_server.py:1504 (direkt/dynamisch unklar); tests/test_server.py:8664 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 20813 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 20814 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 20815 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 20816 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 20817 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 20818 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1319 (direkt/dynamisch unklar); tests/test_server.py:1327 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 20819 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1324 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 20820 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 20821 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 20822 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 20823 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7997 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 20826 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 20830 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:185 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:324 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7999 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 20855 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 20864 | `http_api/` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1283 (direkt/dynamisch unklar); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar); tests/test_server.py:1364 (direkt/dynamisch unklar); tests/test_server.py:1371 (direkt/dynamisch unklar); tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5898 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar); tests/test_server.py:5917 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 20868 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 20878 | `http_api/` | P10 | offen | tests/test_server.py:1325 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 20893 | `performance/` | P3 | offen | tests/test_server.py:7962 (direkt/dynamisch unklar); tests/test_server.py:7972 (direkt/dynamisch unklar); tests/test_server.py:7980 (direkt/dynamisch unklar); tests/test_server.py:7987 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 20935 | `http_api/` | P10 | offen | tests/test_server.py:1289 (direkt/dynamisch unklar); tests/test_server.py:1292 (direkt/dynamisch unklar); tests/test_server.py:1313 (direkt/dynamisch unklar); tests/test_server.py:1346 (direkt/dynamisch unklar); tests/test_server.py:1383 (direkt/dynamisch unklar); tests/test_server.py:3392 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 20961 | `observability.py` | P1 | offen | tests/test_provider_review.py:188 (direkt/dynamisch unklar); tests/test_provider_review.py:191 (direkt/dynamisch unklar); tests/test_provider_review.py:327 (direkt/dynamisch unklar); tests/test_server.py:3389 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 20980 | `observability.py` | P1 | offen | tests/test_server.py:1382 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 20988 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 21000 | `http_api/` | P10 | offen | tests/test_server.py:1364 (direkt/dynamisch unklar); tests/test_server.py:1371 (direkt/dynamisch unklar); tests/test_server.py:3394 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 21006 | `http_api/` | P10 | offen | tests/test_server.py:1264 (direkt/dynamisch unklar); tests/test_server.py:1270 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 21019 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:193 (direkt/dynamisch unklar); tests/test_server.py:1467 (direkt/dynamisch unklar); tests/test_server.py:1762 (direkt/dynamisch unklar); tests/test_server.py:7510 (direkt/dynamisch unklar); tests/test_server.py:7520 (direkt/dynamisch unklar); tests/test_server.py:7526 (direkt/dynamisch unklar); tests/test_server.py:7536 (direkt/dynamisch unklar); tests/test_server.py:7548 (direkt/dynamisch unklar); tests/test_server.py:7553 (direkt/dynamisch unklar); tests/test_server.py:7557 (direkt/dynamisch unklar); tests/test_server.py:7560 (direkt/dynamisch unklar); tests/test_server.py:7566 (direkt/dynamisch unklar); tests/test_server.py:7576 (direkt/dynamisch unklar); tests/test_server.py:7583 (direkt/dynamisch unklar); tests/test_server.py:7590 (direkt/dynamisch unklar); tests/test_server.py:7597 (direkt/dynamisch unklar); tests/test_server.py:8416 (direkt/dynamisch unklar); tests/test_server.py:8439 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 21698 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:193 (direkt/dynamisch unklar) |
| Funktion | `daily_sync_loop` | 21703 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 21716 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 21720 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 21726 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 21732 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 21738 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 21746 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:154 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 21753 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 21767 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 21772 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 21784 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 21796 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 21801 | `sync/` | P6 | offen | tests/test_server.py:978 (direkt/dynamisch unklar); tests/test_server.py:987 (direkt/dynamisch unklar) |
| Funktion | `main` | 21809 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar) |

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
| `backend/runtime` | 2 |
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
| `coach/authorization.py` | 66 |
| `coach/context.py` | 23 |
| `coach/conversation.py` | 8 |
| `coach/dialogue.py` | 18 |
| `coach/jobs.py` | 6 |
| `coach/morning.py` | 26 |
| `coach/proposals.py` | 52 |
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
| `observability.py` | 57 |
| `performance/` | 56 |
| `planning/` | 273 |
| `planning/competitions.py` | 64 |
| `privacy.py` | 4 |
| `providers/` | 93 |
| `providers/calendar.py` | 57 |
| `providers/http.py` | 16 |
| `providers/intervals_client.py` | 1 |
| `providers/workout_text.py` | 13 |
| `runtime/` | 3 |
| `server.py / Composition Root` | 60 |
| `settings.py` | 40 |
| `sync/` | 152 |
| `sync/competitions.py` | 5 |
| `sync/garmin.py` | 106 |
| `sync/scheduler.py` | 15 |
| `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | 3 |
| `weather/` | 55 |

## Grenzen und offene Unsicherheiten

- AST-Aufrufauflösung erfasst nur direkte lokale Aufrufe; `getattr`, `globals()`, `sys.modules`, dekoratorbasierte Registrierung und Callback-Injektion benötigen eine manuelle Nachprüfung.
- Ein Name kann in mehreren Kategorien mit derselben Schreibweise vorkommen; Referenzzählungen sind deshalb namensbasiert und zeigen Ortsangaben, nicht vermeintliche Laufzeitidentität.
- Die Tabelle enthält bewusst auch Importbindungen, damit Rückimporte, spätere Re-Exports und der endgültige Composition-Root-Inhalt überprüfbar bleiben.
- Offene Zielzuordnungen müssen vor dem jeweiligen Umzug fachlich entschieden werden; sie gelten nicht als erledigt.
