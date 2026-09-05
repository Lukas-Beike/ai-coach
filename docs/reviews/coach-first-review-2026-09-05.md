# Coach-first Review und Umsetzung – 5. September 2026

## Ergebnis und Geltungsbereich

**Ausgangsbefund am Commit `270d415`: keine Coach-first-Freigabe.** Bestätigte Defekte betreffen verlorene Sportarten, das Speichern größerer Pläne, die Rückmeldung bereits ausgeführter Aktionen, Nachrichten-Races, Provider-Rohdaten und die lokale Datenlöschung. Die bestehenden Tests decken mehrere dieser Abläufe nicht ab.

Das Review enthält **18 Findings: 5 × P1, 12 × P2, 1 × P3; kein bestätigtes P0**. P1 bedeutet vorrangig vor weiterer Funktionsarbeit beheben; P2 regulär einplanen; P3 gezielte Robustheitsverbesserung. Jeder Befund enthält Fix-Tasks und ein überprüfbares Abnahmekriterium. Die Reihenfolge innerhalb einer Priorität berücksichtigt den Coach als primären Bedienweg.

| Merkmal | Geprüfter Stand |
|---|---|
| Repository | Intervals Coach / `ai-coach` |
| Ausgangsbranch und Commit | `develop`, `270d415bb2d31866ee0548b5107ffd6e3e5fdf71` |
| Anwendung / PWA-Assets | `APP_VERSION = "1.7.2"`; Asset- und Service-Worker-Version `175` |
| Review-/Umsetzungsbranch | `fix/coach-first-review-2026-09-05` |
| Arbeitskopie | `.worktrees/coach-first-review-2026-09-05` im ursprünglichen Checkout |
| Umfang | Gesamte getrackte Anwendung, Backend-Module, Frontend/PWA, Tests, Provideradapter, Docker, CI und Betriebsdokumentation; keine reine Diff-Prüfung |
| Lokale Anwendung | Aus diesem Commit gebautes Image `ai-coach:review-20260905`, SHA `29dd20aea6ee40f14d3d15424f75c8debd0e23e0b934b56742135391683ea72e` |
| Datenmodus | Ausschließlich synthetische Daten und temporäre Testdatenbanken; SQLCipher im Anwendungscontainer aktiv |
| Isolation | Schreibgeschützter Container, temporäres Dateisystem; zunächst `--network none`, für Chromium danach internes Docker-Netz ohne externen Zugang; keine Host-Portfreigabe |
| Nicht benutzt | Reale `.env`, `/data`, Athletendatenbank, Garmin-Tokenstore, Backups, produktive Logs/Diagnoseinhalte und echte Provider-/OpenAI-Aufrufe |
| Ursprüngliche Review-Phase | Dokument und isolierte Prüfskripte; die anschließend autorisierte Umsetzung ist unter „Umsetzungsabnahme“ separat dokumentiert. |

Die Quelltexte im primären Checkout blieben unverändert. Der angelegte Task-Worktree ist ausschließlich lokal über `.git/info/exclude` ausgeblendet, damit er dort nicht versehentlich versioniert wird. Die Review-Container und ihr internes Netz wurden nach den Prüfungen entfernt; der dokumentierte Worktree mit Bericht bleibt erhalten.

Alle Quellverweise und Zeilennummern beziehen sich auf den genannten Commit. „Reproduziert“ bedeutet gezielt ausgelöste Fehler im unveränderten Anwendungscode mit kontrollierten synthetischen Eingaben. Erfolgreiche Defekt-Probes bestätigen den Fehler; sie sind keine grünen Regressionstests für einen Fix. „Statisch“ bedeutet nachvollzogene Implementierung, ohne Behauptung eines beobachteten Fehlers im echten Konto.

## Verbindliches Ziel: frische Anwendung und neue Datenbank

**Nach Anwendung der Fixes beginnt der Betrieb mit einer frischen Anwendung und einer neu angelegten SQLCipher-Datenbank.** Diese Nutzervorgabe vom 5. September 2026 gilt für sämtliche Fix-Tasks und den gesamten verbleibenden Anwendungscode. Bestehender Legacy-Code wird entfernt; er wird weder weiter gepflegt noch hinter Adaptern oder Feature-Flags erhalten. Der Plan sieht keine Übernahme oder Reparatur des bisherigen lokalen Datenbestands vor.

| Bereich | Verbindlicher Umfang der Umsetzung |
|---|---|
| Datenbank und lokale Daten | Ein aktuelles Schema direkt anlegen. Keine Schema-Migrationen, Versionsketten, In-place-Upgrades, automatischen Datenkonvertierungen, Altbestandskorrekturen oder Importe früherer lokaler Datenbanken/Backups. |
| Coach, API und interne Datenverträge | Ein kanonischer Ausführungspfad. Alte Tool-Schemas, Dispatcher, Payload-Varianten, Kompatibilitätsadapter und ausschließlich für frühere Clients vorhandene Routen vollständig entfernen. |
| Anwendung und PWA | Keine eigenen App-Update-/Upgrade-Abläufe und keine Übernahme alter Browser-, Cache- oder Storage-Formate. Erstinstallation, Registrierung des Service Workers, aktuelle statische Assets und Offline-Betrieb bleiben aktuelle Produktfunktionen. |
| Tests und Fixtures | Nur aktuelle Verträge und frisch erzeugte synthetische Daten. Bestehende Upgrade-, Migrations-, Legacy- und Altversionsszenarien einschließlich ihrer Fixtures und Helfer löschen; auch Tests, die ausschließlich die Entfernung früherer Routen oder Symbole prüfen. |
| Betrieb nach dem Neustart | Speichern und Bearbeiten neuer Daten, Provider-Synchronisierung, Wiederholung laufender Aufträge, Prozessneustart mit derselben Anwendungsversion und Backup/Restore des aktuellen Schemas bleiben reguläre Abläufe. Dafür sind weiterhin funktionale Fehler-, Integritäts- und Race-Tests nötig. |

„Update“ bezeichnet hier die Aktualisierung einer bestehenden App-Installation bzw. deren Datenverträge; fachliche Änderungen wie ein bearbeiteter Trainingsplan oder ein neuer Provider-Snapshot gehören weiterhin zur Anwendung. Die Browsermechanik für Service Worker und die Zuordnung aktueller Assets begründen keine zusätzliche Unterstützung früherer App-Versionen. Aktuelle Providerformate und gültige Varianten des gepinnten SDK sind externe Schnittstellenverträge, keine Erlaubnis für alte interne Datenformate.

Die folgenden Findings und Laufzahlen dokumentieren den geprüften Ausgangsstand. Verweise auf alte Pfade dienen ausschließlich als Beleg und Entfernungsinventar. Daraus entsteht keine Anforderung, diese Pfade oder ihre Tests im Zielstand zu behalten. Die anschließend autorisierte Umsetzung und ihre frische lokale Testanwendung sind im folgenden Abschnitt dokumentiert.

## Umsetzungsabnahme

**Die Korrekturen zu allen 18 Findings sind implementiert; 69 von 71 Teilaufgaben sind abgenommen.** Offen sind F16.3 und Q07 wegen noch nicht ausgeführter Betriebsnachweise. Das ist keine Freigabe für ungeprüfte reale Konten oder Geräte.

Alle Anwendungs- und Teständerungen stammen von drei Subagents in eigenen Worktrees. Der Orchestrator hat die Diffs geprüft, konkrete Nachbesserungen zurückgegeben, ihre Commits integriert und die abschließenden Prüfungen selbst ausgeführt. Ein Häkchen wurde erst nach zufriedenstellender Umsetzung und Prüfung gesetzt. Die Befundtexte, Quellverweise und ursprünglichen Abnahmematrizen weiter unten dokumentieren ausdrücklich den Ausgangscommit.

| Paket | Integrierte Commits und geprüfte Wirkung |
|---|---|
| Coach und Planung | `4584f58`, `6f2ef46`, `e8dd640`: ein kanonischer Coach-Pfad; Sport bleibt bis zum Provider-Payload erhalten; bis zu 366 lokale Einheiten atomar; unterschiedliche autorisierte Wirkungen desselben Tools; sessiongebundene dauerhafte Ergebnisse; eindeutige Namensauflösung; eigene Syncjobs lesbar; Undo mit Hash-, Sitzungs-, Ablauf- und Einmalprüfung. |
| Provider, Datenschutz und Login | `6fcab73`, `6ef5c5b`: vollständige Quellen bleiben erhalten; Performance-Merge verwendet den neuesten Snapshot; HRV-Fenster werden korrekt normalisiert; Garmin-Teilquellen behalten letzte gute Werte samt Messdatum; alte Worker und Callbacks können die Löschgrenze nicht überschreiten; UTF-8-Passwortvergleich ohne Schlüsselkonvertierung. |
| Frischer Datenvertrag | `69e2b4a` sowie Coach-/UI-Bereinigung: direkte Anlage genau eines aktuellen SQLCipher-Schemas; keine Migration oder Altbestandsübernahme; tote DB-Aliase, ungenutzter SessionCache, alte Coach-/API-/UI-Pfade und zugehörige Tests entfernt. App-Releaseprüfung und eigene PWA-Updateabläufe entfernt. Aktuelle Registrierung, Offline-Shell und Restore derselben Version bleiben erhalten. |
| Oberfläche und CI | `de12a04`, `2164b2f`, `d2bebaf`, `4851449`, `82a79e3`: Nachrichten-Merge und Generationen, nachgeladene Bereiche, erhaltene Entwürfe, gemeinsame HTTP-/Retry-Fehler, wiederaufnehmbare Belege, verständliche Statusanzeigen und mobile Abbruchbedienung. Der Chat-Reset trennt laufende Polls über eine Request-Identität. Alle CI-Jobs verwenden ausschließlich den Event-SHA; `source_ref`-Dispatch-Overrides und implizite Cache-Poisoning-Pfade sind entfernt. Release-Tag, APP_VERSION, Main-Historie und getesteter SHA bleiben gebunden. |

Der unabhängig geprüfte Anwendungsstand ist `82a79e3` auf `fix/coach-first-review-2026-09-05`; `APP_VERSION` bleibt `1.7.2`, die zusammengehörigen PWA-Assets verwenden Version `177`. Das daraus gebaute Image heißt `ai-coach:pr-20260905`, SHA `51887bf121f839eb2ce5bbb6033806299e8aad28492d9d2003d9e1f4ef4aa6d76`. Die bestehende Installation und ihre Daten wurden nicht verwendet. Für den späteren Betrieb ist entsprechend der Nutzervorgabe ein neuer Datenbestand erforderlich.

### Unabhängige Abschlussprüfungen

| Prüfung | Ergebnis und Aussagegrenze |
|---|---|
| Native vollständige Discovery, Python 3.13 | 423 Tests erfasst, 419 bestanden, vier SQLCipher-spezifische Tests übersprungen; 37,928 Sekunden. |
| CI-Teststart im SQLCipher-Image, Python 3.14 | 423 Tests erfasst, 416 bestanden, sieben Git-spezifische Ref-Tests mangels Git im Laufzeitimage übersprungen; alle SQLCipher-Tests ausgeführt. Die Git-Tests bestehen nativ. Netzwerk gesperrt, schreibgeschützter Container, temporäre Daten. |
| Echter Coverage-/CI-Runner-Aufruf | Erster Shard: 106 Tests bestanden, keine Skips; die CI-Qualit?tsmessung bleibt auf diesen Shard begrenzt. Der zuvor entdeckte fehlende Repository-Importpfad ist korrigiert und durch einen separaten CLI-Prozess aus fremdem Arbeitsverzeichnis abgesichert. |
| Vollständigkeit der Shards | 423 Test-IDs; Verteilung 106/106/106/105; Vereinigung exakt gleich Discovery, keine Duplikate. Importfehler führen zum Fehlerstatus. |
| Syntax und Quality-Baseline | `py_compile` erfolgreich; Ruff, Formatprüfung und Mypy für `tests/run_tests.py` erfolgreich. Die Coverage-Messung betrifft den ersten Shard und ist keine vollständige Coverage-Aussage. |
| Docker-Build | Finales Image erfolgreich gebaut; unveränderte gepinnte Abhängigkeiten und Docker-Basis. |
| Browser, kleinmobil 320×568 | 20/20 bestanden, 24,6 Sekunden. |
| Browser, mobil 390×844 | 20/20 bestanden, 26,0 Sekunden. |
| Browser, Tablet 768×1024 | 20/20 bestanden, 24,1 Sekunden. |
| Browser, Querformat 844×390 | 20/20 bestanden, 24,7 Sekunden. |
| Browser, Desktop 1440×1000 | 20/20 bestanden, 25,8 Sekunden. |
| Zusätzliche Sichtprüfung | Mobile und Desktop-Kalender mit vier tatsächlich über HTTP gespeicherten Sportarten geprüft; lokale IDs und Sportarten wurden zusätzlich automatisiert gegen die API geprüft. |
| Dependency-Prüfung | Python-Audit: 13 Pakete, keine bekannten Schwachstellen gemeldet. npm-Lockfile: sechs Abhängigkeiten, keine bekannten Schwachstellen gemeldet. Requirements, Lockfile und Docker-Basis wurden anschließend unverändert verifiziert. Kein vollständiger Betriebssystem-/Lizenzaudit. |
| Abschlussinventar | Kein verbleibender zweiter Coach-Pfad, keine App-Updateprüfung, keine Migrations-/Altversions-Tests in den geprüften aktuellen Quellen. `cipher_compatibility = 4` legt aktuelle SQLCipher-4-Parameter fest und ist kein Upgradepfad. Historische Handover-Belege sind ausdrücklich abgelöst. |

Jeder Browser-Viewport lief mit einer neu erzeugten SQLCipher-Datenbank im selben finalen Build. Das interne Docker-Netz hatte keinen externen Zugang. Die Browser-Vertragstests verwenden frisch erfasste lokale Leseprojektionen für kontrollierte Races; der Runtime-Smoke prüft echte HTTP-/SQLCipher-Pfade. Dazu gehören der Commit von vier Sportarten, GET und sichtbarer Kalender sowie idempotente Wiederholung. Verlorene Modellzusammenfassungen und geschützte Aktionen sind durch Backendtests plus Browser-Vertragstests abgesichert; ein echter Responses-Aufruf ist damit nicht behauptet.

Die zusätzlichen Browserfälle prüfen unter anderem verspätete History, neue Entwürfe während Ablehnungen, die vollständige HTTP-Fehlermatrix, JSON-/HTML-/unvollständige Erfolgsantworten, Retry-After, Reload mit Teilbeleg, sichtbare mobile Abbruchbedienung, verspätete Sitzung-/Transkriptionsantworten, zwei Tabs mit Leasewechsel, Quellenalter, Offline-Rückkehr desselben Builds und den Status verbrauchter/abgelaufener Freigaben. Der Login-Accessibility-Test prüft jetzt den tatsächlich sichtbaren Anmeldedialog.

Die Abnahme erforderte Nachbesserungen: Ein offenes Test-Loghandle, der direkte CI-Importpfad, überlappende Objektnamen, Quellenalter in Coach-Projektionen und verlorene Undo-Bestätigungen wurden nach unabhängiger Prüfung repariert. Browser-Tests wurden gegen frisch erfasste Leseprojektionen isoliert, nachdem viele Testanfragen das unveränderte Rate-Limit erreicht hatten. Die abschließenden Läufe oben sind erfolgreich; frühere Fehlversuche werden daraus nicht als Erfolg abgeleitet.

### Offene Betriebsnachweise

- **F16.3:** Lokale Ref-/Tag-/Versions-, Branchverschiebungs- und fehlende-Tag-Verträge sind geprüft. Ein tatsächlicher nicht veröffentlichender GitHub-Dispatch des neuen Workflow-Stands wurde nicht ausgeführt. Der Task bleibt deshalb offen.
- **Q07:** Reale Provider-/Responses-Testkonten, physische HTTPS-/PWA-/Voice-/Notification-Geräteabläufe und der GitHub-Dispatch bleiben ausstehend. Der vorhandene HTTPS-Health-Endpunkt antwortete vor Integration mit HTTP 502; die getestete lokale Anwendung war vollständig isoliert. Ein vollständiger binärer Browser-Backup/Restore-Roundtrip wurde ebenfalls nicht zusätzlich ausgeführt; aktuelle SQLCipher-Backup-/Restorefunktionen sind isoliert getestet. Der Dependency-Teil ist abgeschlossen.

Die lokalen Nachweisdateien liegen unter `C:/Users/Work/AppData/Local/Temp/coach-implementation-validation-20260905/`: Build-, Native-, Container-, Quality- und fünf Browserlogs sowie `final-mobile.png` und `final-desktop.png`. Sie enthalten ausschließlich synthetische Testzustände. Die temporäre Testinstanz und ihr internes Docker-Netz wurden nach der Abnahme entfernt. Der Bericht und die Anwendungskorrekturen sind auf dem Task-Branch versioniert; PR #383 wurde erstellt und wartet auf die externen GitHub-Checks.

## Findings und Fix-Tasks

### F01 · P1 · Coach-Pläne verlieren ihre Sportart und werden als Radfahren gespeichert

**Ort:** [server.py:8097](../../server.py#L8097), [server.py:8865](../../server.py#L8865), [server.py:8879](../../server.py#L8879), [server.py:9020](../../server.py#L9020). **Sicherheit:** hoch; vollständiger lokaler Stage/Commit-Pfad reproduziert und im Browser sichtbar.

`normalize_workout()` erzeugt die Sportart im Feld `sport`. Beim Anlegen einer datierten Einheit delegiert `normalize_planned_unit()` an `normalize_library_workout()`. Dessen Allowlist behält `type`, aber nicht `sport`; ein fehlender Typ wird zu `Ride`. Anschließend kopiert `normalize_planned_unit()` diesen bereits falschen Typ nach `sport`. Der eigentlich vorhandene Lauf-/Kraft-/Indoor-/Schwimmsport wird damit ersetzt.

**Reproduktion:** Je einen ausdrücklich autorisierten Plan mit `Run`, `WeightTraining`, `VirtualRide` und `Swim` stagen und committen. Bei allen vier Sportarten sind danach **`type = Ride`, `sport = Ride` und der erzeugte Remote-Event-Payload `type = Ride`**. Kein Remote-Aufruf wurde ausgeführt. In der gefüllten Browseranwendung erscheinen die als `Run` angelegten Einheiten entsprechend als „Radfahren“.

Das beeinträchtigt Plananzeige, sportbezogene Auswertung und einen später ausdrücklich beauftragten Export. Die vorhandenen Sporttests für importierte Einheiten liefern bereits `type` und erfassen diesen lokalen Coach-Pfad nicht.

- [x] **F01.1:** Einen eindeutigen aktuellen Sportvertrag durch Coach, Normalisierung, Persistenz und UI führen; den validierten Coach-Sport erhalten und das Intervals-Feld `type` an der Providergrenze ausdrücklich zuordnen. Keine Fallbacks für frühere gespeicherte Workout-Formate ergänzen.
- [x] **F01.2:** Den vollständigen Weg vom strukturierten Tool-Payload über Stage/Commit und SQLite bis zu Kalenderprojektion und Remote-Payload für alle unterstützten Sportarten prüfen.
- [x] **F01.3:** Im Browser explizit die sichtbare Sportart gegen die synthetische Eingabe prüfen; Layout- und axe-Erfolg allein erkennen diesen fachlichen Fehler nicht.

**Abnahme:** Ein Laufplan bleibt vom Coach-Auftrag bis zum späteren Intervals-Payload ein Laufplan; dasselbe gilt für Kraft, Indoor-Rad und andere unterstützte Sportarten.

### F02 · P1 · Leistungs-Refresh ersetzt den vollständigen Intervals-Snapshot durch eine reduzierte Fassung

**Ort:** [server.py:7954](../../server.py#L7954), [server.py:11097](../../server.py#L11097), [SnapshotRepository.save:239](../../backend/db/repositories.py#L239). **Sicherheit:** hoch; reproduziert.

`fetch_performance_snapshot(existing)` baut einen neuen kompakten Snapshot. Es übernimmt Aktivitäten und Kalender für die Anzeige, aber weder `raw_provider_data` noch das vorhandene `provider_sync.calendar_window` und weitere vollständige Snapshot-Metadaten. `refresh_current_performance()` speichert diesen Wert als neuesten Snapshot. Die Snapshot-Retention behält nur zwölf Fassungen; die alte vollständige Fassung ist damit kein dauerhafter Ersatz.

**Auslöser und Wirkung:** Nach einem vollständigen Intervals-Import wird „Leistungsdaten aktualisieren“ ausgeführt. Im Probe waren die Rohdaten und das geladene Kalenderfenster vorher vorhanden und danach im Ergebnis entfernt. Rohdaten-basierte Ableitungen und die Nachvollziehbarkeit der ursprünglichen Daten werden beeinträchtigt. Das ist eine Änderung an der gespeicherten Quelle, obwohl die Reduktion nur den Coach-Kontext betreffen soll. Der normale inkrementelle Aktivitätssync besitzt dagegen einen Rohdaten-Merge und ist nicht pauschal von diesem Befund betroffen.

- [x] **F02.1:** Leistungsmetriken gezielt in den vollständigen neuesten Snapshot einarbeiten oder getrennt persistieren; Rohdaten, historisches Fenster und Kalender-Metadaten erhalten.
- [x] **F02.2:** Beim Commit gegen den inzwischen aktuellen Snapshot mergen. `PERFORMANCE_LOCK` und `SYNC_LOCK` allein verhindern kein Überschreiben eines zwischenzeitlich neueren Aktivitätssnapshots.
- [x] **F02.3:** Regressionstest mit Rohdaten, älterem Backfill und Kalenderfenster; danach Leistungs-Refresh und Prüfung der vollständigen Quelle. Zusätzlich einen langsamen Performance-Refresh mit dazwischen abgeschlossenem Aktivitätssync verschachteln.

**Abnahme:** Ein Leistungs-Refresh ändert ausschließlich seine Leistungsfelder/Freshness; neue Aktivitäten und vollständige Ursprungsdaten bleiben erhalten. Der konkurrierende Überschreibpfad wurde statisch geprüft, die Feldverluste wurden dynamisch reproduziert.

### F03 · P1 · Erfolgreiche Tool-Mutationen werden nach einem OpenAI-Folgefehler nicht als Ergebnis ausgeliefert

**Ort:** [server.py:14452](../../server.py#L14452), [server.py:14496](../../server.py#L14496), [server.py:14523](../../server.py#L14523), [server.py:16767](../../server.py#L16767), [public/app.js:3590](../../public/app.js#L3590). **Sicherheit:** hoch; reproduziert.

Das strukturierte Tool speichert seine Änderung und seinen Beleg vor der nächsten Responses-Anfrage. Scheitert diese Folgeanfrage, persistiert `_persist_structured_command_failure()` die Belege zwar intern; beim interaktiven Turn wird aber keine dauerhafte Assistant-Ergebnisnachricht angelegt. Das SSE-Fehlerereignis liefert nur Fehlertext und Reason. History und Chat-Status stellen diese bereits erfolgreichen Command-Receipts nicht für die Wiederaufnahme bereit.

**Reproduktion:** `save_checkin` erfolgreich ausführen, die anschließende Modellanfrage mit einem synthetischen 503 abbrechen. Ergebnis: **1 gespeicherter Check-in, 1 erfolgreicher interner Beleg, 0 Assistant-Nachrichten**. Der Nutzer kann die Aktion für gescheitert halten und erneut senden. Bei Erstellaktionen mit neuer Turn-ID drohen doppelte Einträge; ein gleicher Tages-Check-in wird dagegen erneut aktualisiert.

- [x] **F03.1:** Für jeden Turn ein abfragbares, sessiongebundenes Ergebnis mit Status je Mutation bereitstellen und es auch bei Modellfehler, Abbruch, Disconnect und Reload ausliefern.
- [x] **F03.2:** Nach bereits bestätigten Writes eine deterministische lokale Ergebnisnachricht erzeugen, wenn die sprachliche Modellzusammenfassung ausfällt. Erfolg, Fehler und noch nicht ausgeführte Schritte getrennt benennen.
- [x] **F03.3:** Wiederaufnahme/Wiederholung an die vorhandene Turn-/Operations-ID binden; bereits gespeicherte Ergebnisse im UI zeigen, bevor eine erneute Erstellaktion angeboten wird.
- [x] **F03.4:** Regressionstest „Write erfolgreich → Folge-503/Timeout → Browser-Reload“; Änderung genau einmal vorhanden und erfolgreicher Beleg ohne Modellantwort sichtbar.

**Abnahme:** Ein Fehler der Zusammenfassung kann keine erfolgreich ausgeführte lokale Aktion als unbekannten Gesamtausfall erscheinen lassen.

### F04 · P1 · Ein laufender Schreiber kann gelöschte Daten nach der Datenschutz-Löschung wieder eintragen

**Ort:** [server.py:16221](../../server.py#L16221), [server.py:11094](../../server.py#L11094), [MaintenanceGate:241](../../server.py#L241). **Sicherheit:** hoch; reproduziert.

`delete_local_data()` serialisiert nur die eigentlichen SQL-Deletes. Es wartet nicht exklusiv auf bereits laufende Provider-/Coach-Operationen und verwirft deren spätere Commits nicht. Der HTTP-Pfad benutzt eine normale Maintenance-Operation; damit dürfen andere normale Operationen parallel weiterlaufen.

**Reproduktion:** Einen gemockten Leistungs-Refresh vor seiner Antwort anhalten, lokale Daten löschen, dann den alten Refresh freigeben. Die Löschung meldet Erfolg und der Snapshot ist zunächst leer; nach Abschluss des alten Workers enthält er wieder **1 Aktivität**, ohne Worker-Fehler. Das ist vom absichtlichen späteren Neuladen durch einen neuen Sync zu unterscheiden.

- [x] **F04.1:** Lokale Komplettlöschung mit einer exklusiven Wartungsphase koordinieren: neue Mutationen sperren, laufende Operationen kontrolliert beenden/abwarten und erst danach löschen.
- [x] **F04.2:** Vor der Löschgrenze gestartete Queue-Einträge, offene Coach-Turns und In-Memory-Callbacks durch eine Generation/Abbruchgrenze von späteren Writes ausschließen; keine zuvor gelöschten Payloads erneut verwenden.
- [x] **F04.3:** Regressionstests mit angehaltenem Provider-Refresh und Coach-Tool, jeweils vor und nach dessen Write-Grenze. Nach erfolgreicher Löschung dürfen alte Worker keine Athletendaten neu anlegen.

**Abnahme:** Der bestätigte Löschzeitpunkt bildet eine konsistente Grenze. Eine spätere ausdrücklich oder planmäßig gestartete neue Synchronisierung bleibt ein eigener Vorgang.

### F05 · P1 · Vorbereitete Pläne mit mehr als 28 Einheiten können nicht gespeichert werden

**Ort:** [server.py:13788](../../server.py#L13788), [server.py:14014](../../server.py#L14014), [server.py:14441](../../server.py#L14441). **Sicherheit:** hoch; reproduziert.

Beim Staging sind bis zu 366 Einheiten zugelassen. `commit_training_plan` prüft dann das gesamte Artefakt erneut mit dem Limit von 28 Einheiten pro Kommando. Eine Aufteilung des Artefakts beim Commit fehlt. Mehrfaches Aufrufen desselben mutierenden Tools im Turn wird zusätzlich gesperrt.

**Reproduktion:** Einen validen Plan mit 29 Einheiten an 29 verschiedenen Tagen vorbereiten und denselben Plan explizit speichern. Staging erfolgreich; Commit **400 / `plan_limit`**, **0 gespeicherte Einheiten**. Damit scheitert z. B. ein Acht-Wochen-Plan mit vier Einheiten pro Woche am zentralen Coach-Bedienweg. Die vorhandene Aufteilung des späteren Remote-Pushs behebt den lokalen Commit nicht.

- [x] **F05.1:** Den autorisierten Artefakt-Commit in begrenzte, vollständig nachvollziehbare Teiloperationen aufteilen oder innerhalb einer begrenzten Transaktion den gesamten zulässigen lokalen Plan übernehmen.
- [x] **F05.2:** Gesamtvalidierung, Konfliktprüfung, Artefaktrevision und Wiederaufnahme über alle Teile erhalten; bei Teilfortschritt exakte IDs und Fortschritt persistieren.
- [x] **F05.3:** 28, 29 und 56 Einheiten sowie einen Fehler/Neustart zwischen Teilen prüfen; keine verlorenen oder doppelt gespeicherten Einheiten und keine impliziten Remote-Writes.

**Abnahme:** Ein ausdrücklich zum Speichern beauftragter zulässiger Mehrwochenplan wird im selben logischen Auftrag vollständig lokal gespeichert oder als konkret nachvollziehbarer Teilfehler gemeldet.

### F06 · P2 · Eine ältere History-Antwort blendet neue Nutzer- und Assistant-Nachrichten aus

**Ort:** [public/app.js:3510](../../public/app.js#L3510), [public/app.js:1802](../../public/app.js#L1802), [public/app.js:1816](../../public/app.js#L1816), [public/app.js:3324](../../public/app.js#L3324). **Sicherheit:** hoch; Browser-Reproduktion auf allen fünf Viewports.

Optimistische Nutzernachrichten werden ohne persistierte ID in `state.data.messages` ergänzt. Ein History-Load ersetzt anschließend die ganze Liste. Die Lade-Sequenz schützt gegenüber anderen Loads, aber nicht gegenüber einer inzwischen gestarteten oder abgeschlossenen Chat-Generation. `renderMessages()` ergänzt die aktive `chatRequest.message` nicht wieder. Auch eine bereits über `completed` eingefügte Assistant-Nachricht wird durch eine ältere History-Liste entfernt.

**Reproduktionen:** (1) Nachricht senden, danach eine ältere leere History freigeben: Die Nutzer-Bubble verschwindet, obwohl der Request ihre Nachricht noch hält. (2) History vor dem Abschluss starten, `completed` mit neuer ID verarbeiten, dann die alte History freigeben: Die sichtbare Assistant-Bubble verschwindet bis zum neueren Abgleich. Der zweite Ablauf wurde dreimal je Viewport erzwungen. Nachgewiesen ist ein Verlust im sichtbaren Clientzustand, nicht das Löschen der Nachricht aus SQLite.

- [x] **F06.1:** Nachrichten über persistierte ID und `client_turn_id` zusammenführen; aktive optimistische Nachrichten als eigene Zustände bis zur bestätigten Übernahme behalten.
- [x] **F06.2:** History-Antworten an Chat-/Request-Generation oder einen Server-Watermark binden. Eine ältere Antwort darf neuere bestätigte Nachrichten nicht zurücknehmen.
- [x] **F06.3:** Beide Interleavings als Browser-Regressionsfälle mit steuerbaren History-Barrieren aufnehmen; zusätzlich Sync-Refresh und Navigation während des Streams verschachteln.

**Abnahme:** Eine gesendete oder bereits bestätigte Nachricht bleibt ohne Flackern vorhanden, bis ein ausdrücklicher Reset/Löschvorgang sie entfernt; Stream und persistierte Antwort erscheinen genau einmal.

### F07 · P2 · HTTP-Ablehnungen beim Chat werden als Verbindungsabbruch behandelt; Entwurf und Fehlermeldung gehen verloren

**Ort:** [public/app.js:3533](../../public/app.js#L3533), [public/app.js:3614](../../public/app.js#L3614), [public/app.js:3436](../../public/app.js#L3436), [public/app.js:3688](../../public/app.js#L3688). **Sicherheit:** hoch; reproduziert.

Bei einer nicht erfolgreichen HTTP-Antwort setzt der Client `stream.serverError` nur für 401. Alle übrigen HTTP-Ablehnungen geraten in den Recovery-Pfad. Der Entwurf wurde vorher geleert; wenn der Status anschließend `idle` meldet und keine neue History existiert, wird auch die optimistische Nachricht verworfen. Die konkrete Serverfehlermeldung wird dabei nicht angezeigt.

**Reproduktion:** Für `/api/chat/stream` nacheinander **400, 403, 404, 409, 413, 422, 429, 500, 502, 503 und 504** injizieren. Auf allen fünf Viewports endet der Client mit leerem Eingabefeld, ohne Nutzer-Bubble und ohne die eingespeiste Fehlererklärung. 401 wurde separat als Rückkehr zum Login geprüft. Diese Probe betrifft HTTP-Ablehnungen vor einem angenommenen Stream; SSE-Fehler nach Annahme sind ein anderer Pfad.

- [x] **F07.1:** Definitive HTTP-Ablehnung, nachweislich angenommener Auftrag und unklarer Transportabbruch unterscheiden. Nur den letzten Fall anhand derselben Turn-ID abgleichen.
- [x] **F07.2:** HTTP-Status, sicheren `reason`, verständlichen Fehlertext und gegebenenfalls Retry-Information bis ins UI erhalten.
- [x] **F07.3:** Nicht angenommene Nachrichten als editierbaren Entwurf oder sichtbaren fehlgeschlagenen Eintrag mit Wiederholung behalten; einen inzwischen neu geschriebenen Entwurf nicht überschreiben.
- [x] **F07.4:** Die Statusmatrix sowie Timeout vor/nach Serverannahme testen. 409/429 müssen einen nachvollziehbaren erneuten Versuch ermöglichen.

**Abnahme:** Ein 400 ist als Validierungsfehler erklärbar; kein abgelehnter Auftrag verschwindet wortlos.

### F08 · P2 · Garmin-HRV im Dictionary-Format wird beim Zusammenführen verworfen

**Ort:** [backend/providers/garmin.py:65](../../backend/providers/garmin.py#L65), [server.py:4010](../../server.py#L4010), [server.py:4341](../../server.py#L4341). **Sicherheit:** hoch für den Formatfehler; tatsächliche Antwortform eines Live-Kontos nicht geprüft.

Der installierte, gepinnte Garmin-Client deklariert `get_hrv_data_range` als `dict | None`. Der Collector übernimmt ein Dictionary zunächst unverändert, bei mehreren Fenstern jedoch nur das erste. Anschließend akzeptiert `_merge_garmin_records()` ausschließlich Listen und ersetzt eine solche Dictionary-Antwort durch eine leere Liste. Eine erfolgreiche Anfrage kann so HRV liefern, während der gespeicherte Snapshot keine HRV enthält.

**Reproduktion:** `{"hrvSummaries": [{"calendarDate": "2026-09-05", "weeklyAvg": 50}]}` durch den produktiven Merge schicken: **0 Records**. Es wird nicht behauptet, dass jedes Garmin-Konto genau diese Form liefert; eine bereits listenförmige Antwort nimmt einen anderen Pfad.

- [x] **F08.1:** Antwortformen im Garmin-Adapter explizit normalisieren, einschließlich enthaltener `hrvSummaries`; alle abgefragten Fenster zusammenführen.
- [x] **F08.2:** Unbekannte Formen als unvollständigen Import markieren und letzte gute Daten behalten. „HTTP erfolgreich“ darf nicht automatisch „Daten vollständig“ bedeuten.
- [x] **F08.3:** SDK-nahe Dictionary-, Listen-, Leer- und Fehlantworten sowie zwei Fenster und einen Fensterfehler prüfen; Datum, Quellenlabel und letzte gültige Werte erhalten.

**Abnahme:** Unterstützte HRV-Antwortformen werden vollständig übernommen; unerwartete Formen werden sichtbar und datenerhaltend behandelt.

### F09 · P2 · Garmin-Deduplizierung verändert die gespeicherten Originaldaten

**Ort:** [server.py:3343](../../server.py#L3343), [server.py:4248](../../server.py#L4248), [server.py:4352](../../server.py#L4352). **Sicherheit:** hoch; reproduziert.

Sowohl im Fixture- als auch im SDK-Sync werden gegen Intervals passende Garmin-Aktivitäten entfernt, bevor `garmin_snapshot` gespeichert wird. Eine separate vollständige Rohfassung fehlt. Einzelne abgeleitete Maximalpulswerte werden gerettet; das erhält die ursprünglichen Garmin-Datensätze mit ihren weiteren Feldern nicht.

**Reproduktion:** Eine synthetische Garmin-Aktivität mit zusätzlichem Garmin-Feld und eine passende Intervals-Aktivität synchronisieren. Ergebnis **1 eingehende, 0 gespeicherte Garmin-Aktivitäten**, Zusatzfeld nirgendwo im Snapshot erhalten, Status `ok`. Die dynamische Probe nutzt den Fixture-Zweig; der SDK-Zweig führt dieselbe Filterung vor dem Speichern aus.

- [x] **F09.1:** Vollständige Garmin-Quelle vor der Deduplizierung persistieren. UI-/Coach-Projektion separat erzeugen und kanonische Zuordnung als Referenz/Metadatum speichern.
- [x] **F09.2:** Die Begrenzung auf fünf aktuelle Aktivitäten pro Sport ausschließlich in der Coach-Projektion belassen; keine Rohdatenretention daraus ableiten.
- [x] **F09.3:** Regression mit überlappender Aktivität und Garmin-spezifischen Feldern; Kontext zeigt keine doppelte Einheit, die Originalquelle bleibt unverändert abrufbar.

**Abnahme:** Deduplizierung spart Kontext und doppelte Darstellung, ohne eine Providerquelle zu vernichten.

### F10 · P2 · Ein ungültiger Vorlagen-Batch hinterlässt schon gespeicherte Einträge

**Ort:** [server.py:14039](../../server.py#L14039), [server.py:9123](../../server.py#L9123), [server.py:14460](../../server.py#L14460). **Sicherheit:** hoch; reproduziert.

`manage_training_templates` verarbeitet die Vorlagen nacheinander. Jeder Create/Update kann seine eigene Transaktion abschließen. Die Validierung einer späteren Vorlage findet erst danach statt. Bei einem Fehler verwirft der Dispatcher die gesammelte Ergebnisliste und liefert einen einzigen Fehler zurück.

**Reproduktion:** Zwei Vorlagen übergeben: erste gültig, zweite unzulässig datiert. Das Tool antwortet mit 400; **eine Vorlage bleibt gespeichert**, ohne dass der Fehlerbeleg deren Erfolg und ID ausweist.

- [x] **F10.1:** Gesamten Batch vor dem ersten Write normalisieren und validieren; bei gewünschtem Alles-oder-nichts-Verhalten eine gemeinsame Unit of Work verwenden.
- [x] **F10.2:** Falls Teilfortschritt bewusst erlaubt wird, pro Objekt einen dauerhaften Erfolgs-/Fehlerbeleg samt ID zurückgeben und nur fehlgeschlagene Objekte erneut ausführen.
- [x] **F10.3:** Fehler im zweiten und letzten Batch-Element testen. Ergebnis und tatsächliche Datenbankänderung müssen exakt übereinstimmen.

**Abnahme:** Ein fehlgeschlagener Batch kann keine nicht ausgewiesenen gespeicherten Vorlagen hinterlassen.

### F11 · P2 · Zwei ausdrücklich beauftragte Aktionen desselben Tool-Typs werden als Duplikat gesperrt

**Ort:** [server.py:14441](../../server.py#L14441), [server.py:14464](../../server.py#L14464). **Sicherheit:** hoch; reproduziert.

`executed_tools` speichert Tool-Namen. Der zweite Aufruf eines mutierenden Namens wird unabhängig von Ziel, Argumenten und `call_id` als `duplicate_tool_call` abgelehnt. Mehrere Vorlagen besitzen einen Batch-Eingang, Check-ins und Wettkämpfe dagegen jeweils nur einen einzelnen Payload.

**Reproduktion:** In einem ausdrücklich autorisierten Turn zwei Check-ins für verschiedene Tage speichern. Der erste wird persistiert; der zweite endet mit **409 / `duplicate_tool_call`**. Entsprechende Mehrfachaufträge für andere einzelne Mutationen sind ebenfalls durch den Namen-Guard blockiert.

- [x] **F11.1:** Wiederholung derselben Wirkung anhand von Turn, Tool, Ziel-ID und kanonischen Argumenten erkennen; unterschiedliche autorisierte Ziele nicht allein wegen eines gleichen Tool-Namens sperren.
- [x] **F11.2:** Für natürliche Mehrfachaufträge begrenzte Batch-Schemas anbieten und deren Teilergebnisse mit F03/F10 konsistent machen.
- [x] **F11.3:** Zwei verschiedene Check-ins/Wettkämpfe im selben Turn sowie die Wiederholung desselben `call_id` testen. Verschiedene Wirkungen müssen ausgeführt, echte Duplikate verhindert werden.

**Abnahme:** „Speichere beide …“ funktioniert innerhalb des expliziten Umfangs, ohne Idempotenz aufzugeben.

### F12 · P2 · Die Intent-Stufe kann notwendige Objekt-IDs nicht auflösen; neu erzeugte Sync-Jobs sind für den Coach nicht lesbar

**Ort:** [backend/coach/intent.py:77](../../backend/coach/intent.py#L77), [server.py:14585](../../server.py#L14585), [server.py:14601](../../server.py#L14601), [server.py:14101](../../server.py#L14101), [server.py:14154](../../server.py#L14154), [server.py:14453](../../server.py#L14453). **Sicherheit:** hoch für die Scope-Inkonsistenz; reale Modellklassifikation nicht ausgeführt.

Der isolierte Intent-Request erhält die aktuelle Nachricht, erlaubte Provider und Plan-Artefaktreferenzen. Wettkampfnamen/-IDs, Change-IDs und Jobreferenzen fehlen. Für das Ändern eines Wettkampfs verlangt der Handler aber einen exakten `competition:<id>`-Scope; der für Erstellen/Löschen unterstützte Scope `local_competitions` reicht hier nicht. Ein Name aus der Nutzernachricht kann damit nicht verlässlich auf die erforderliche UUID abgebildet werden, bevor der Scope feststeht.

Zusätzlich erzeugt ein ausdrücklich beauftragter Refresh eine neue Job-ID, ergänzt aber keinen Scope für diesen Job. `get_sync_job` fordert genau diesen Scope. Die Hauptschleife erweitert den Scope ausschließlich für neu angelegte Plan-Artefakte.

**Probes:** Wettkampfänderung mit `local_competitions` → **403 / `intent_scope_denied`**; gültig beauftragten Refresh enqueuen und dessen zurückgegebene Job-ID lesen → ebenfalls **403 / `intent_scope_denied`**. Die Probes belegen die Handler-Grenze, nicht eine gemessene Häufigkeit natürlicher Fehlklassifikationen.

- [x] **F12.1:** Vor der Autorisierung eindeutige lokale Namen/Referenzen sicher auf konkrete IDs auflösen; bei mehreren Treffern eine konkrete Rückfrage stellen. Keine Objekt-UUID vom Modell erraten lassen.
- [x] **F12.2:** Für im autorisierten Turn erzeugte Jobs den Lesezugriff explizit session-/turngebunden ergänzen. Fremde Jobs bleiben außerhalb dieses Umfangs.
- [x] **F12.3:** Intent- und Handler-Verträge für Create/Update/Delete vereinheitlichen; ausgewählte Objekte nicht durch pauschale neue Schreibrechte ersetzen.
- [x] **F12.4:** End-to-End-Fixtures für „Benenne Wettkampf X um“ und „Aktualisiere Garmin und melde das Ergebnis“ erstellen; keine manuell in den Prompt kopierten UUIDs voraussetzen.

**Abnahme:** Der Coach kann eindeutig benannte Objekte bearbeiten und den eigenen Refresh verfolgen, ohne interne Identifikatoren vom Nutzer zu verlangen.

### F13 · P2 · Der strukturierte Undo-Pfad liefert seine Bestätigung nicht an die UI

**Ort:** [server.py:14215](../../server.py#L14215), [server.py:2851](../../server.py#L2851), [server.py:14500](../../server.py#L14500), [public/app.js:3585](../../public/app.js#L3585). **Sicherheit:** hoch; reproduziert.

`undo_training_change` erzeugt einen sessiongebundenen `proposed_action` über `_history_preview`. Das Ergebnis verbleibt verschachtelt im Tool-Beleg. Die strukturierte Abschlussantwort setzt `proposed_actions` auf eine separate Liste und übernimmt diesen Vorschlag nicht. Die UI rendert nur diese oberste Liste; die allgemeine Tool-Beleganzeige erzeugt daraus keinen ausführbaren Undo-Dialog.

**Reproduktion:** Eine lokale Vorlagenänderung anlegen und ihren Undo im strukturierten Coach-Turn vorbereiten. Ergebnis: **verschachtelter Vorschlag vorhanden, `proposed_actions` = 0**. Die Änderung wurde noch nicht rückgängig gemacht und ihre erforderliche Bestätigung fehlt im Chat. Der manuelle Weg über Änderungshistorie/Preview ist davon getrennt.

- [x] **F13.1:** Vorschläge aus strukturierten Tool-Ergebnissen in den kanonischen UI-Aktionsvertrag übernehmen und bei Reload anhand der ursprünglichen Session wiederherstellen.
- [x] **F13.2:** Vorschau, erforderliche explizite Freigabe, Einmaltoken und veraltete Objekt-Hashes beibehalten; Vorschlag und bereits ausgeführtes Undo unterschiedlich anzeigen.
- [x] **F13.3:** „Änderung rückgängig machen“ vom Chat bis zur freigegebenen lokalen Änderung prüfen, einschließlich Reload vor Bestätigung und Ablehnung eines veralteten Tokens.

**Abnahme:** Ein Coach-Undo endet mit einer sichtbaren nächsten Aktion oder einem bestätigten Ergebnis; eine Textbehauptung allein reicht nicht.

### F14 · P2 · Navigation und direkte Domain-Loads verlieren angeforderte Bereiche während eines laufenden Loads

**Ort:** [public/app.js:110](../../public/app.js#L110), [public/app.js:3324](../../public/app.js#L3324), [public/app.js:3378](../../public/app.js#L3378). **Sicherheit:** hoch; reproduziert.

`load()` gibt bei beliebiger laufender `state.loadPromise` deren Promise zurück, auch wenn ein anderer Bereich angefordert wurde. `ensureRouteData()` kehrt bei dieser Situation ebenfalls früh zurück. Ein anschließendes Nachladen für diese Aufrufer wird nicht vorgemerkt. Der spezielle SSE-State-Event-Pfad besitzt hingegen bereits eine Queue und ist nicht pauschal betroffen.

**Reproduktion:** Chat-/History-Load anhalten, währenddessen `plan` und `library` anfordern, ersten Load beenden. Ergebnis: **0 Aufrufe von `/api/plan`**. Beim entsprechenden Navigationswechsel kann die neue Ansicht leer oder veraltet bleiben, bis ein weiteres Ereignis sie tatsächlich lädt.

- [x] **F14.1:** Laufende und ausstehende Bereiche getrennt erfassen; nach dem aktuellen Load die Vereinigung noch fehlender Bereiche abarbeiten.
- [x] **F14.2:** Eine Bereichsversion erst übernehmen, wenn genau die dazugehörigen Daten erfolgreich eingearbeitet wurden. Mit dem Nachrichten-Merge aus F06 koordinieren.
- [x] **F14.3:** Navigation Chat → Geplant während verzögerter History sowie gleichzeitige Profil-/Sync-Refreshes testen; angeforderte Bereiche müssen ohne erneutes Verlassen/Öffnen geladen werden.

**Abnahme:** Jeder angeforderte Bereich wird geladen oder zeigt seinen eigenen erklärbaren Fehlerzustand.

### F15 · P2 · Ein zulässiges Passwort mit Nicht-ASCII-Zeichen verhindert die Anmeldung

**Ort:** [server.py:1378](../../server.py#L1378), [server.py:16395](../../server.py#L16395). **Sicherheit:** hoch; reproduziert.

Die Konfiguration akzeptiert Passwörter ab zwölf Zeichen ohne ASCII-Beschränkung. `login_user` übergibt beide Passwörter aber als Python-Strings an `hmac.compare_digest`. Nicht-ASCII-Zeichen lösen dort `TypeError` aus. Die Anwendung kann mit dem Schlüssel konfiguriert sein, die HTTP-Anmeldung scheitert dennoch mit einem internen Fehler.

**Reproduktion:** Ausschließlich synthetisches Passwort mit Umlaut und ausreichender Länge verwenden; `login_user` wirft **TypeError** statt erfolgreichem bzw. negativem Vergleich.

- [x] **F15.1:** Beide Vergleichswerte konsistent als UTF-8-Bytes vergleichen. Für die neue SQLCipher-Datenbank und die Anmeldung dasselbe unveränderte konfigurierte Passwort verwenden; keine stille Unicode-Normalisierung oder Schlüsselkonvertierung einführen.
- [x] **F15.2:** ASCII, Umlaut und Emoji sowie falsche Varianten und Längengrenzen testen; Fehler dürfen weder Passwort noch Schlüssel in Logs ausgeben.

**Abnahme:** Jedes von der Startvalidierung akzeptierte Passwort kann unverändert zur Anmeldung verwendet werden.

### F16 · P2 · Manueller Container-Publish kann einen anderen Commit bauen als den geprüften

**Ort:** [publish-container.yml:45](../../.github/workflows/publish-container.yml#L45), [publish-container.yml:51](../../.github/workflows/publish-container.yml#L51), [publish-container.yml:76](../../.github/workflows/publish-container.yml#L76), [publish-container.yml:254](../../.github/workflows/publish-container.yml#L254). **Sicherheit:** hoch; statisch nachgewiesen, kein Workflow ausgelöst.

Bei `workflow_dispatch` verwendet der Test-Shard-Checkout bevorzugt `source_ref`. Die Versionsprüfung findet dort statt. Andere Prüfjobs verwenden den Default-Checkout, der Publish-Job dagegen `release_tag`. Wenn diese Referenzen auf verschiedene Commits zeigen, kann ein grüner Teststand einen anderen Build freigeben. Die erfolgreiche Versionsprüfung beweist dann nicht, dass `APP_VERSION` des tatsächlich gebauten Tags passt.

- [x] **F16.1:** Zu Beginn genau einen unveränderlichen Quell-SHA auflösen; denselben SHA an Syntax-, Unit-, SQLCipher-, Quality-, Browser- und Build-Jobs weitergeben.
- [x] **F16.2:** Vor Veröffentlichung nochmals am Build-Checkout `APP_VERSION` gegen den Release-Tag und den Event-SHA gegen den geprüften SHA prüfen. Ein frei wählbarer `source_ref`-Override ist entfernt; der Workflow führt ausschließlich den eigenen unveränderlichen Event-SHA aus.
- [ ] **F16.3:** Den Ref-Auflösungsvertrag mit unterschiedlichen Branch-/Tag-SHAs, verschobenem Branch und falscher Tag-Version testen; anschließend einen nicht veröffentlichenden Dispatch prüfen.

**Abnahme:** Image, Versionsprüfung und alle erforderlichen Checks beziehen sich nachweislich auf denselben Commit.

### F17 · P2 · Der CI-Test-Runner lässt 13 Tests aus anderen Modulen aus

**Ort:** [tests/run_tests.py:11](../../tests/run_tests.py#L11), [tests/run_tests.py:37](../../tests/run_tests.py#L37), [publish-container.yml:70](../../.github/workflows/publish-container.yml#L70). **Sicherheit:** hoch; Loader und Testinventar geprüft.

Der Shard-Runner lädt ausschließlich `test_server` über `loadTestsFromModule`. Die reguläre Discovery findet dagegen vier Module: **410 + 7 + 3 + 3 = 423 Tests**. Die sieben Intent-Tests, drei DB-Manager-Tests und drei Sync-Job-Tests werden über diesen Runner nicht ausgeführt. Beide lokalen Discovery-Läufe dieses Reviews haben alle vier Module einbezogen.

- [x] **F17.1:** Vor dem stabilen Sharding eine vollständige `test_*.py`-Discovery durchführen; Test-IDs weiterhin deterministisch sortieren.
- [x] **F17.2:** Prüfen, dass die Vereinigung aller Shards exakt der Discovery-Menge entspricht und jeder Test genau einmal vorkommt. Importfehler müssen den Job fehlschlagen lassen.
- [x] **F17.3:** Neu angelegte Testmodule in diesem Abgleich automatisch erfassen; SQLCipher-Skips und tatsächliche Laufzahlen explizit ausweisen.

**Abnahme:** Ein Defekt in Intent, DB-Manager oder Job-Vertrag kann nicht wegen eines ausgelassenen Moduls unbemerkt grüne CI ergeben.

### F18 · P3 · Erfolgreicher HTTP-Status mit ungültigem JSON wird als leeres Erfolgsobjekt akzeptiert

**Ort:** [public/api.js:13](../../public/api.js#L13), [public/app.js:3873](../../public/app.js#L3873). **Sicherheit:** hoch; Fehler-Injektion im Browser.

`AppApi.request` fängt einen JSON-Parsefehler ab und ersetzt ihn durch `{}`. Ist der HTTP-Status erfolgreich, wird dieses Objekt regulär zurückgegeben. Speichern-Aufrufer wie `saveProfile` können daraufhin Erfolg anzeigen und den Dirty-Status entfernen, obwohl keine verwertbare Bestätigung vorliegt.

**Reproduktion:** Auf einen PUT einen 200-Status mit ungültigem JSON liefern: Der API-Helper löst mit `{}` auf. Ein solcher Body wurde nicht vom normalen Anwendungsserver beobachtet; geprüft ist die Behandlung einer fehlerhaften HTTP-/Proxyantwort.

- [x] **F18.1:** JSON-Parse-/Vertragsfehler bei erwarteten JSON-Antworten als eigenen Fehler behandeln; dokumentierte leere Antworten ausdrücklich separat zulassen.
- [x] **F18.2:** Bei Speicheraktionen erforderliche Erfolgsfelder prüfen und den Entwurf bis zur validen Bestätigung behalten.
- [x] **F18.3:** 200 mit ungültigem JSON, HTML-Fehlerseite und syntaktisch gültigem, aber unvollständigem Objekt prüfen.

**Abnahme:** Ein erfolgreiches HTTP allein reicht nicht aus, um eine fehlerhafte Speicherbestätigung als Erfolg darzustellen.

## Umsetzung in sinnvoller Reihenfolge

| Paket | Findings | Konkretes Ergebnis |
|---|---|---|
| 0. Neustart und vollständige Bereinigung | N01–N08 unten; verbindlich für alle Findings | Ein aktuelles Schema und ein Coach-Pfad; kein Update-, Migrations- oder Legacy-Code und keine zugehörigen Szenarientests |
| 1. Datenintegrität | F01, F02, F04, F09, F08 | Erhaltene Sportarten und Providerquellen, konsistente Löschgrenze, robuste Garmin-Formate |
| 2. Verlässliche Coach-Aufträge | F03, F05, F10, F11 | Vollständige lokale Pläne und wahrheitsgetreue, wiederaufnehmbare Teilergebnisse |
| 3. Chat- und Ladezustand | F06, F07, F14, F18 | Keine durch ältere Antworten verschwindenden Nachrichten; nutzbare Fehler-/Retry-Anzeige |
| 4. Tool-Parität und Zugang | F12, F13, F15 | Auflösung benannter Objekte, eigene Jobstatus, ausführbares Undo, Unicode-Login |
| 5. Verifikation und Veröffentlichung | F17, F16 | Vollständige Test-Discovery und ein gemeinsamer geprüfter Build-SHA |

Paket 0 beginnt vor den fachlichen Fixes und gilt bei deren Umsetzung weiter: Auch kleine Fixes dürfen keinen zweiten Vertrag oder Übergangspfad einführen. F17 ebenfalls früh umsetzen, damit die bereinigte Suite und die zusätzlichen Regressionstests tatsächlich CI erreichen. Die dokumentierten 423 Tests beschreiben ausschließlich den Ausgangsstand; nach der Entfernung veralteter Tests wird das Inventar neu ermittelt. Eine unveränderte Testanzahl ist kein Abnahmekriterium.

### Paket 0: konkrete Entfernungs- und Abnahmeaufgaben

- [x] **N01 – Nur das aktuelle Datenmodell:** `initialise_database()` und alle Persistenz-/Restorepfade auf direkte Anlage und Nutzung genau eines aktuellen Schemas begrenzen. Der geprüfte Startup erzeugt bereits direkt das Schema und enthält keine Schema-Migration ([server.py:1623](../../server.py#L1623)). Etwaige verbleibende Konvertierungs-, Nachfüll- oder Reparaturpfade für frühere interne Datenformen vollständig entfernen. SQLCipher, Schlüsselprüfung und Integritätsvalidierung behalten; Schemaabweichungen lösen keine Konvertierung oder automatische Neuerstellung aus. Es gibt keinen Import des bisherigen lokalen Bestands.
- [x] **N02 – Einen Coach-Ausführungspfad herstellen:** Den zweiten Zweig von `chat_with_coach()` ohne `client_turn_id`, `COACH_TOOLS`, `COACH_PROPOSAL_TOOLS`, `COACH_INTENT_TOOL_MAP`, `requested_coach_tool()` und ausschließlich dafür verwendete Schemas, Auswahlregeln und Dispatcher entfernen. Zuvor die noch benötigten Aufrufer an den kanonischen Vertrag anschließen: insbesondere den automatischen Morgen-Check-in ([server.py:15269](../../server.py#L15269)) mit eigener Operationsidentität und verbindlich schreibgeschütztem Berechtigungsumfang. Fachlich gemeinsam benötigte Operationen genau einmal implementieren. Adaptive Änderungen und Undo behalten ihre speziellen Freigaben; ein eindeutiger, benannter Remote-Sync bleibt durch den natürlichen Auftrag autorisiert.
- [x] **N03 – Historische Chat-Sonderbehandlung entfernen:** Die Filter für früher als `role=event` gespeicherte Syncmeldungen in [paged_chat_history:9304](../../server.py#L9304) und [ChatRepository.list:168](../../backend/db/repositories.py#L168) samt Altbestandskommentaren und zugehörigen Fixtures entfernen. Noch vorhandene Erzeuger solcher Meldungen auf den aktuellen Operations-/Statuskanal ausrichten. Die neue Nachrichtenpersistenz erhält einen eindeutigen Rollenvertrag; keine Bereinigung oder Umschreibung alter Chatzeilen.
- [x] **N04 – Veraltete Verträge vollständig löschen:** Aufrufer in Backend, Frontend, Tools und Tests gemeinsam verfolgen und nicht mehr benötigte API-Aliase, interne Feldvarianten, Wrapper, Default-Übersetzungen und doppelte Implementierungen entfernen. Aktuelle Aufrufer direkt an den endgültigen Vertrag anpassen; keine Übergangsadapter, Dual-Reads, Dual-Writes oder versteckten Altpfade. Aktuelle Provider-Normalisierung gezielt an der Providergrenze erhalten. F01/F08 werden gegen aktuelle Eingaben und SDK-Verträge abgesichert.
- [x] **N05 – Eigene App-Update-Abläufe entfernen:** `showPwaUpdate()`, `setupPwaUpdates()` und `applyPwaUpdate()` einschließlich Update-Button, Events, Reload-/`SKIP_WAITING`-Handshake und ausschließlich dafür vorgesehenen Tests entfernen ([public/app.js:3896](../../public/app.js#L3896), [public/service-worker.js:10](../../public/service-worker.js#L10)). Die notwendige Erstregistrierung separat für den aktuellen Service Worker erhalten. Keine Übernahme, Konvertierung oder gezielte Unterstützung alter Asset-, Browser- oder Storage-Generationen ergänzen. Die zusammengehörigen aktuellen Assetreferenzen, den Cache und den Offline-Start einer frischen Installation konsistent halten.
- [x] **N06 – Tests und Testhilfen bereinigen:** `test_chat_history_excludes_legacy_sync_events_before_pagination` ([tests/test_server.py:1411](../../tests/test_server.py#L1411)) und `test_obsolete_direct_planning_routes_are_removed` ([tests/test_server.py:7834](../../tests/test_server.py#L7834)) löschen. Sämtliche Tests des entfernten Coach-Zweigs sowie weitere Update-/Migrations-/Altversionsfixtures und ausschließlich zugehörige Helfer entfernen. Weiterhin relevante fachliche Assertions als Tests des aktuellen kanonischen Ablaufs mit frisch erzeugten Daten formulieren. Keine Ersatztests anlegen, die historische Schemas, Routen oder entfernte Symbole katalogisieren. Allgemeine Validierung fehlerhafter aktueller Eingaben und beschädigter Dateien bleibt erforderlich.
- [x] **N07 – Dokumentation auf den Zielstand bringen:** README, aktive Betriebsanweisungen, Skills, Fix-/Handoverpläne und Testanleitungen auf frische Installation und genau einen aktuellen Vertrag ausrichten. Anweisungen zu Migration, Upgrade, Altbestandsreparatur und Pflege alter Pfade entfernen. Die Review-Vorlage nennt bislang „compatibility or migration concerns“, die Restore-Checkliste „migration compatibility“; diese Vorgaben in den aktiven Skill-Referenzen ebenfalls streichen. Historische Review-Belege bleiben als solche gekennzeichnet. Die neue Anwendung erhält ein leeres Datenverzeichnis und ein frisches Browserprofil; der Plan enthält keine Lösch- oder Konvertierungsskripte für den bisherigen Bestand.
- [x] **N08 – Den bereinigten Zielstand abnehmen:** Aus dem endgültigen Quellstand ein neues Docker-Image bauen und mit leerem temporärem Datenverzeichnis, SQLCipher und synthetischer Konfiguration starten. Aktuelle Unit-Discovery/CI-Shards abgleichen, Syntax prüfen und die Coach-, Fehler-, Integrations- und UI-Abnahmen dieses Berichts mit neu erzeugten Daten ausführen. Neustarts und Wiederaufnahme verwenden ausschließlich denselben Build; Restore-Fixtures entstehen aus dessen frisch angelegter Datenbank. Abschließend Quellcode, Tests und aktive Dokumentation auf verbliebene Übergangs-/Legacypfade prüfen. Diese einmalige Review-Prüfung wird nicht als dauerhafte Altversions-Testmatrix implementiert.

**Abnahme für Paket 0:** Im ausgelieferten Anwendungscode existieren ausschließlich die aktuellen Daten-, Tool-, API- und UI-Verträge. Neue SQLCipher-Datenbank und frische Browserinstallation genügen für alle vorgesehenen Abläufe. Weder Start noch Restore oder Coach-Verarbeitung benötigen ein früheres Schema, eine Konvertierung, einen alten Dispatcher oder eine ältere Clientversion. Die Test-Suite enthält keine Update-, Migrations- oder Legacy-Szenarien. Ein neuer Betrieb wird erst nach Umsetzung und Prüfung der Findings begonnen; dieser Bericht führt ihn nicht aus.

## Architektur und Abdeckungsnachweis

Der Browser verwendet die Hash-Routen Coach, Heute, Geplant/Übersicht/Bibliothek, Analyse/Leistung/Verlauf und Mehr mit Unterseiten. `public/app.js` koordiniert deren Zustand, parallele Loads, SSE, Spracheingabe und Benutzeraktionen; `api.js`, `state.js`, `navigation.js`, `views.js`, `forms.js` und `components.js` enthalten extrahierte Teilverantwortungen. `server.py` bleibt die Grenze für Authentifizierung, HTTP, Datenbankzugriff, Geschäftsoperationen, Provider und Responses-Lifecycle. `backend/` kapselt zusätzliche DB-, Provider-, Kontext-, Job-, HTTP- und Exportprimitive.

Persistente Daten umfassen Profil/KV, Wettkämpfe/Tombstones, Snapshots, Vorlagen und geplante Einheiten, Pläne/Revisionen, Check-ins, Feedback, Anpassungsvorschauen, Kalenderquellen/-kandidaten/-ereignisse, Sessions, Änderungshistorie, Tool-Belege, Coach-Kommandos/-Artefakte/-Vorschläge sowie Sync-Jobs/-Items/-Cursor und bereinigten Providerverlauf. OpenAI-Konversationen sind Dialogkontinuität; bestätigtes lokales Athletenwissen bleibt in SQLite. Voice-Audio wird nicht als Datei oder Datenbankobjekt persistiert.

**Legende:** S = Quellcode/Vertrag nachvollzogen; U = einschlägige vorhandene Unit-/Container-Tests ausgeführt; R = zusätzliche Defekt-Reproduktion; B = Browser mit synthetischer Anwendung; blockiert = konkreter noch fehlender Laufzeitnachweis. „Ohne weiteren Befund“ bedeutet keine zusätzliche belegte Fehlfunktion, keine Garantie der Fehlerfreiheit.

| Nr. | Prüffeld | Hauptbelege | Validierung und Ergebnis | Verbleibende Grenze |
|---|---|---|---|---|
| 1 | Produktgrenzen und Architektur | `AGENTS.md`, `server.py`, `backend/`, README, Handovers | S/U; lokal autoritative Planung und explizite Providerwrites nachvollzogen; F05/F12/F13 | Natürlichsprachliche Toolwahl des echten Modells blockiert ohne Provideraufrufe |
| 2 | Auth, Sessions, CSRF, HTTP | RequestHandler, Login/Session-Funktionen, `backend/http_api/`, Auth-Tests | S/U/B/R; fehlende/fremde CSRF-Tokens, Sessionablauf, Logout, parallele Sessionnutzung; F15 | Reale HTTPS-Proxy-Cookie-Konfiguration nicht aus `.env` gelesen |
| 3 | Geheimnisse, Datenschutz, untrusted input | Redaction/Logging/Capture, Privacy, Views/Markdown, Kalendertransport | S/U/B/R; F04; XSS-Payload im Browser inert, Exportgrenzen geprüft | Keine produktiven Logs, Diagnoseexports oder echten Athletenpayloads geöffnet |
| 4 | SQLCipher und dauerhafte Daten | Schema/Startup, DB-Manager/Repositories, Write-Pfade | S/U/R; SQLCipher-Checks im Container; F02/F09/F10 | Zielabnahme mit neu angelegter Datenbank; Kompatibilität mit früheren Datenbeständen gehört ausdrücklich nicht zum Auftrag |
| 5 | Backup/Restore | Restorevalidierung, Maintenance-Gate, Export-Modul, SQLCipher-Tests | S/U; Integrität/Fremdschlüssel/exaktes Schema, Drain, Recoverykopie, Sessioninvalidierung geprüft | Browser-Upload eines Backups nicht ausgeführt; echte Backups ausgeschlossen |
| 6 | Provider und Netzgrenzen | Intervals-/Garmin-/Kalenderadapter, `http_json`, Wetter/GitHub/Responses | S/U/R; gepinnte Garmin-Methoden lokal inspiziert; F08 | Live-Schemas, reale Quoten, MFA, DNS-/Proxybetrieb nicht verifiziert |
| 7 | Sync und Nebenläufigkeit | Provider-Gates, Startup/Daily, Jobs/Retry/Cursor, Frontend-Status | S/U/R/B; F02/F04/F12/F14 | Mehrprozessbetrieb und tatsächlicher Provider-Restart-Fortschritt nicht ausgeführt |
| 8 | Coach-Kontext und Provenienz | `backend/coach/context.py`, Kontextaufbau, Garmin-/Leistungsprojektion | S/U; Quellenlabels, lokale Wahrheit, fünf neueste Aktivitäten pro Sport; F02/F09 betreffen vorgelagerte Quelle | Keine Qualitätsbewertung realer Trainingsratschläge oder medizinischer Aussagen |
| 9 | Responses und sämtliche Tools | Intent-Modul, Tool-Schemas/Dispatcher, Streams/Background/Receipts | S/U/R/B; F03/F05/F10/F11/F12/F13 | Keine echten Responses-/Conversations-Aufrufe; Modellentscheidungen separat blockiert |
| 10 | Planung, Wettkämpfe, Kalender | Lokale Mutationen, expliziter Push, Adaptive Preview/Apply, Undo | S/U/R/B; Hash-/Revision-/Tombstone-/Remote-write-Grenzen geprüft; F01/F05/F10/F11/F12/F13 | Tatsächliche Remote-Geräteauslieferung und Kontenkonflikte nicht ausgeführt |
| 11 | Datum, Zeitzonen, Einheiten | `local_now`, Datumsschlüssel, Recurrence, Metrics/Weather, Tests | S/U; DST-Rekurrenz, date-only-Darstellung, Check-in-Grenzen und Einheiten geprüft | Reise über Profil-/Gerätezeitzonen im echten Browser sowie verzögerte Vorschaufreigabe nach Tageswechsel nicht dynamisch ausgeführt |
| 12 | Frontendzustand und API | Alle HTTP-Routen, `api.js`, Loader/Chat/Profile, DOM-Sinks | S/U/B/R; F06/F07/F14/F18; Fehlerklassen und sichtbare Entwürfe geprüft | Nicht jede Route als realer Browser-Wire-Test ausgeführt; Einzelnachweise unten |
| 13 | PWA und Offline | SW/Manifest/Assets und Connectivity-Code; vorhandener Update-Pfad als Entfernungsumfang N05 | S/U/B; aktuelle Assets konsistent, kein API-Cache | Frische Geräteinstallation und OS-Push nicht vollständig geprüft; Versionswechsel alter Installationen sind kein weiterer Prüfauftrag |
| 14 | Zuverlässigkeit, Leistung, Diagnose | Locks/Queues/Bounds, Redaction, History/Pagination, Worker | S/U/R; F02/F03/F04/F06/F10/F14 | Kein End-to-End-Latenz-/Speicherbenchmark mit realistischem Langzeitdatenbestand; keine Performancegewinne behauptet |
| 15 | Tests und Aussagekraft | Vier Unit-Module, Shard-Runner, E2E/Fixtures und Assertions | S/U/B/R; F17; reproduzierte Defekte trotz bestehender grüner Suites | Statische Analyse nicht neu vollständig über die Anwendung ausgeführt; CI-Quality-Scope ist wesentlich kleiner als die Codebasis |
| 16 | Abhängigkeiten und Container | Requirements/Lockfiles, Dockerfile/Ignore, Loginhelper, Startskripte | S/U/B; Build, Python 3.13/3.14 und read-only Runtime geprüft | Kein aktueller CVE-/Lizenzdatenbankabgleich und kein kompletter Supply-Chain-Scan |
| 17 | CI, Releases, GitHub-Aktionen | Sämtliche sechs Workflows, Dependabot und Review-Prompt | S; Permissions, Ref-Fluss, Version/Tag und Fail-Closed-Gates; F16/F17 | GitHub-App-Rechte, Branchschutz und tatsächliche Workflowausführung nicht online verifiziert |
| 18 | Dokumentation und Wartbarkeit | README, `.env.example`, Task/Handover, scoped AGENTS, Paketkonfiguration | S; Produktversprechen gegen reale Pfade abgeglichen; Abweichungen den Findings zugeordnet | Ältere Handover-/Task-Aussagen sind keine Zusicherung des heutigen Laufzeitverhaltens |

### Coach-Fähigkeiten und Tool-Parität

Referenzen: [Intent-Vertrag](../../backend/coach/intent.py), [strukturierte Schemas:13629](../../server.py#L13629), [Dispatcher:13944](../../server.py#L13944), [Loop:14224](../../server.py#L14224). Der reguläre HTTP-Chat verlangt `client_turn_id` und erreicht den strukturierten Pfad. Alle **27 kanonischen Tool-Namen** wurden mit Enum, Schema, Auswahl, Handler und Ergebnisverarbeitung abgeglichen. S/U in der Tabelle bedeutet nicht, dass jede konkrete Kombination natürlichsprachlich mit einem echten Modell durchlaufen wurde.

Gemeinsame Grenzen: aktuelle explizite Intent-Autorisierung plus Objekt-/Operations-Scope; ausschließlich Lesen bei Rat/Unklarheit; lokale Mutationen vor Remote-Sync; Sessionbindung für Vorschläge und Jobs; Tool-Ergebnisse werden gespeichert und als `function_call_output` zurückgeführt. Payload-Objekte einzelner Schemas delegieren die Detailvalidierung an den Handler. Das ist besonders bei Batch- und Error-Pfaden relevant.

| Tool | Eingabe / fachlicher Handler | Autorisierung und Wirkung | Ergebnis-/Testnachweis |
|---|---|---|---|
| `read_training_state` | leer; `_structured_training_state` | Read; lokale Revision, Einheiten/Vorlagen, Referenzen | S/U; begrenzter lokaler Zustand; keine Providerwrites |
| `list_recent_activities` | Tage/Limit; vorhandene Aktivitätsprojektion | Read; bestätigte Provider-Snapshots | S/U; Paging/Quellen; Ursprungsdaten können durch F02/F09 fehlen |
| `list_workout_library` | Limit/Archivfilter | Read; lokale wiederverwendbare Vorlagen | S/U; kein neuer Remote-Import erzwungen |
| `list_planned_workouts` | Limit | Read; lokale geplante Einheiten | S/U; lokale IDs/Sync-Status |
| `list_change_history` | Limit | Read; begrenzte Änderungsreferenzen | S/U; Werte für Undo verbleiben serverseitig |
| `list_competitions` | leer | Read; lokal bestätigte Wettkämpfe | S/U; Update-Auflösung gesondert F12 |
| `list_training_plans` | leer | Read; lokale Planmetadaten | S/U; lokale Zuständigkeit nachvollzogen |
| `stage_training_plan` | `payload` mit Plan/Workouts | Lokaler Plan-Scope; persistiertes Artefakt, noch kein Workout-Push | S/U/R; bis 366 Staging-Einheiten; F05 |
| `commit_training_plan` | `artifact_id` | Autorisierter Commit; Artefakt/Conversation/Revision prüfen; lokale Einheiten anlegen | S/U/R; Sportartverlust F01; expliziter gleicher Turn unterstützt, >28 scheitert: F05 |
| `apply_training_changes` | `changes`, `expected_revision` | Lokaler Plan-/Objekt-Scope; begrenzter Batch | S/U; vorhandener Test belegt Rollback bei spätem Fehler; vom Vorlagen-Batch F10 unterscheiden |
| `manage_training_templates` | `template` oder `templates` | Lokaler Vorlagen-Scope; Create/Update/Archiv/Restore/Delete | S/U/R; F10; kein impliziter Remote-Push |
| `save_checkin` | `payload` | `local_checkin`; lokale Tagesbeobachtung, Datum/Skalen validiert | S/U/R; F03/F11; Zukunftsdatum-Regeln getestet |
| `save_activity_feedback` | Payload bzw. Aktivitäts-ID/Name/Datum/Notizen | `activity_feedback`; bekannte Aktivität erforderlich | S/U; lokaler Feedback-Beleg, leere Notizen löschen |
| `delete_activity_feedback` | `activity_id` | Explizites Entfernen plus Feedback-Scope | S/U; kanonischer Feedback-Write-Pfad |
| `save_competition` | `payload` einschließlich optionaler `competition_id` | Expliziter lokaler Auftrag; Create breit, Update exakter Scope | S/U/R; F12; zweite gleiche Mutation zusätzlich F11 |
| `delete_competition` | `competition_id` | Expliziter Auftrag; Objekt oder lokaler Wettbewerbsscope; lokaler Delete/Tombstone | S/U; Remote-Löschung erst beim ausdrücklich benannten Sync |
| `start_provider_refresh` | Tage/Grund; Provider aus Intent | Ausschließlich namentlich erlaubter Provider-Refresh | S/U/R; queued Job statt Warten; eigener Statuszugriff F12 |
| `refresh_current_performance` | Grund | `intervals_refresh`; eigener Jobtyp | S/U/R; F02; kein OpenAI-basierter Leistungsersatz |
| `start_intervals_plan_sync` | optionale ausgewählte IDs/Hashes, Grund | Explizites Intervals-Ziel und Plan-/Objekt-Scope | S/U; begrenzte 28er Push-Jobs, IDs/Status als Beleg; Read-Sync erzeugt diese Writes nicht |
| `sync_competitions` | Grund | Explizites Intervals-Ziel plus `local_competitions` | S/U; Wettbewerbspush mit verknüpften IDs/Tombstones |
| `get_sync_job` | `job_id` | Read, aber exakter Job-Scope | S/R; neuer eigener Job wird mit aktuellem Scope abgelehnt: F12 |
| `resolve_training_sync_conflict` | lokale ID oder Job-ID, `keep_local`/`adopt_remote` | Expliziter aufgelöster Objekt-/Job-Scope | S/U; lokale Konfliktlösung und vorhandene Idempotenztests; natürlicher Referenzweg mit F12 absichern |
| `preview_adaptive_replan` | leer | Explizite Vorschau; keine Workout-Änderung | S/U; gespeicherte Vorschau mit Fingerprints |
| `apply_adaptive_replan` | Anpassungs-ID, optionale Illness-Sync-Angabe | Explizite Freigabe des Previews; Remote-SICK nur bei separat benanntem Intervals-Sync | S/U; alte/geänderte/gelöschte Ziele und Wiederholung geprüft; Tageswechsel-Lücke unten |
| `update_training_plan` | Plan-ID/`payload` | Explizite lokale Metadatenänderung | S/U; Plan löschen entfernt Metadaten, nicht pauschal seine Einheiten |
| `undo_training_change` | Change-ID | Scope + sessiongebundene Vorschau/Einmaltoken | S/U/R; Beleg enthält Vorschlag, UI erhält ihn nicht: F13 |
| `apply_workout_library_plan` | Eintrags-/Datumsarray | Explizites lokales Einplanen, Konfliktprüfung | S/U; keine Remote-Kalenderwrites ohne gesonderten Sync |

**Entfernungsinventar des geprüften Ausgangsstands:** Die 25 älteren `COACH_TOOLS` samt zweitem Ausführungspfad werden gemäß N02 vollständig gelöscht. Ihre sechs List-Tools haben kanonische Pendants; Refreshes werden fachlich durch `start_provider_refresh`, Plan-/Workout-Schreiboperationen durch Stage/Commit, Change-Batch und Vorlagenverwaltung abgedeckt. Check-in, Feedback, adaptive Aktionen, Wettbewerbssync/-CRUD, Planmetadaten und Bibliotheksplanung bleiben über den aktuellen Vertrag erreichbar. `sync_workout_library` hat sein fachliches Gegenstück im ausdrücklich benannten Planungspush. Für das alte `refresh_workout_library` wird kein Kompatibilitätsalias geschaffen; die Bibliothek ist lokal autoritativ. Diese Zuordnung begründet die Entfernung doppelter Implementierungen, keinen zu erhaltenden Übersetzungslayer. Die aktuellen Fähigkeiten werden nach der Bereinigung ausschließlich über den kanonischen Intent-/Scope-Pfad geprüft.

Profil, Modell-/Thinking-Auswahl, Kalenderanzeige, Datenschutz, Backup/Restore und Diagnose bleiben explizite UI/API-Aktionen. Ihr Fehlen als generisches Coach-Schreibtool ist kein pauschales Finding. Die gesondert bestätigte Entfernung einer Wahoo/Garmin-Doppelaufzeichnung sowie Undo/Adaptive-Approval wurden als spezielle Grenzen geprüft; routinemäßige lokale Planänderungen dürfen daraus keine zusätzliche allgemeine Preview/Confirm-Schleife erben.

### Nachrichten-Lifecycle und Interleavings

Alle folgenden Wiederaufnahme-, veralteten Antwort- und Race-Szenarien entstehen innerhalb derselben aktuellen Anwendungsversion mit neu erzeugten Daten. Sie beschreiben keine Versionsübergänge oder Übernahme alter Installationen.

Der Sollpfad lautet: Entwurf → lokal sichtbar/queued → sessiongebundene Serverannahme mit Turn-ID → Stream oder dauerhafter Hintergrundjob → persistierte Tool-Ergebnisse → persistierte Antwort → Zusammenführung mit History. Transportverlust darf einen angenommenen Auftrag nicht erneut erstellen. Ein abgelehnter Auftrag muss dagegen editierbar oder eindeutig fehlgeschlagen bleiben.

| Szenario | Ausgeführter Nachweis | Befund / verbleibende Grenze |
|---|---|---|
| Enter sendet, Shift+Enter erzeugt Zeilenumbruch | B, alle fünf Viewports | Geprüft; IME-Komposition zusätzlich S, keine echte IME-Geräteprüfung |
| Nachricht senden während Antwort läuft | B; Queue-Reihenfolge ausgelesen und Folgeturns abgeschlossen | FIFO für normale Einreihung geprüft |
| Steuern während Antwort läuft | B; priorisierten Eintrag vor FIFO ausgeführt | Priorisierter Folgeturn, keine heimliche Änderung des bereits laufenden Prompts |
| Derselbe `completed`-Beleg zweimal | B; drei Folgeturns, jedes Abschlussereignis doppelt | Genau eine Assistant-Bubble je ID im geprüften Ablauf |
| Optimistische Nachricht versus ältere History | R/B, 5 Viewports | F06; Nachricht verschwindet |
| `completed` versus schon laufende alte History | R/B, 3 Wiederholungen × 5 Viewports | F06; bestätigte Antwort wird aus der UI entfernt |
| Bootstrap/Domain-Load versus Navigation | R/B, kontrollierte Ladebarriere | F14; angeforderte Plan-Daten werden nicht geholt |
| State-SSE-Refresh während anderem Load | S; `scheduleStateEventRefresh` besitzt Nachholqueue | Dieser spezielle Pfad bereits abgesichert; nicht mit F14 gleichsetzen |
| Stream während Tabwechsel, lange Markdown-Antwort und Scrollen | Vorhandene B-Suite, alle Viewports | Stabile DOM-Darstellung im dort getesteten Ablauf |
| Transportabbruch nach Delta, Antwort bereits in SQLite/History | B mit synthetischer persistierter History | Antwort einmalig wiederhergestellt; kein neuer Modellauftrag nötig |
| HTTP-Ablehnung vor Annahme | R/B, elf Statuscodes × 5 Viewports | F07; Fehler/Entwurf verloren |
| Explizites Abbrechen | B und U | Abbruch-UI, serverseitiges Response-Schließen und keine Ausführung partieller Toolargumente geprüft |
| Browserverbindung schließt ohne Abbruchwunsch | U (`test_disconnected_chat_stream_continues_and_does_not_cancel_provider_work`) | Serverseitige Arbeit läuft weiter; echte Geräteverbindung nicht verwendet |
| Reload eines Hintergrundjobs | U, dauerhafter Job und Statuspfad | Response-ID/sessiongebundene Wiederaufnahme in Mocks geprüft; vollständiger Browser→echtes Modell→Reload blockiert |
| Prozessneustart eines Hintergrundjobs | U (`test_interrupted_background_coach_job_resumes_openai_response_id`) | Persistierte Response-ID im Test wiederverwendet; kein realer laufender OpenAI-Job neu gestartet |
| Tool-Write erfolgreich, Folgeantwort scheitert | R | F03; gespeicherte Wirkung ohne sichtbaren Erfolgsbeleg |
| Zwei gleiche Tool-Typen mit unterschiedlichen Zielen | R | F11; zweites Ziel wird abgelehnt |
| Session läuft ab / 401 während einer UI-Anfrage | U/B | Login sichtbar, App ausgeblendet und `state.data` geleert |
| Zwei Sessions, fremde Operation abbrechen | U | Status und Operations-ID sessiongebunden; fremder Abbruch abgelehnt |
| Zwei echte Browsertabs, Broadcast/Lease-Wechsel gleichzeitig mit Completion | S | **Nicht dynamisch ausgeführt:** eigener kontrollierter Zwei-Tab-/Lease-Test fehlt; nicht als bestanden gezählt |
| Sichtbarkeit/Offline und Rückkehr | S; Pausebedingungen und Wiederanlauf geprüft | Browser-Recovery im internen Netz geprüft; echter Hintergrund-/Suspend-Lifecycle des Mobil-OS blockiert |
| Chat-Reset gleichzeitig mit aktivem/queued Hintergrundjob | S | **Nicht dynamisch ausgeführt:** koordinierter Reset-/Worker-Test fehlt; getrennt vom bestätigten Datenschutz-Race F04 behandeln |
| Späte Antwort einer alten Session nach erneutem Login | S | **Nicht dynamisch ausgeführt:** alte Stream-/Load-Callbacks über Login-Grenze gezielt halten; kein behaupteter Datenabfluss |

Die vorhandene Browser-Suite fand F06 nicht: Ihr kontrollierter History-Inhalt enthält im Abschlussablauf bereits die neue Antwort. Die zusätzlichen Probes lassen dagegen eine tatsächlich ältere Antwort zuletzt ankommen.

### Frontend-/Backend-API-Verträge

Inventar: [GET-Routing:16491](../../server.py#L16491), [POST-Grenze:16606](../../server.py#L16606), [POST-Dispatcher:16779](../../server.py#L16779), [PUT-Routing:16870](../../server.py#L16870), [API-Client](../../public/api.js). Erfasst sind **24 GET-Verträge, 28 POST-Verträge einschließlich des ausdrücklich abgelehnten POST-Statuspfads und 5 PUT-Verträge**. Abgesehen von Health/Readiness/Auth-Status/Login verlangen sie eine Session; alle mutierenden HTTP-Pfade zusätzlich CSRF. Restore hat eine exklusive Wartungsgrenze, Chat-Cancel bleibt während laufender Arbeit erreichbar. Private JSON-Antworten werden nicht gecacht.

Gemeinsame Fehlergrenze: JSON muss ein Objekt sein, Größen und Content-Type werden geprüft. `AppError`-Antworten vieler JSON-Routen liefern nur `error`; der sichere maschinenlesbare `reason` geht am HTTP-Rand verloren. SSE besitzt dagegen ein eigenes `error`-Ereignis. F07/F18 beschreiben die daraus unabhängig belegten Clientdefekte. Ein S-Eintrag ist ein statischer Routen-/Aufrufervergleich, kein behaupteter HTTP-Lauf für jeden Zweig.

| Methode / Route | Aufrufer und Eingabe | Erfolgsvertrag / Prüfung |
|---|---|---|
| GET `/api/health` | Infrastruktur, keine Session | Kleine Liveness-/Maintenance-Antwort; S/U, Fixture-Runtime gestartet |
| GET `/api/readiness` | Infrastruktur, keine Session | Sichere Readiness-Booleans, 200/503; S/U, Schema-/Wartungsfehler geprüft |
| GET `/api/auth/status` | Login/Initialisierung | Authentifiziert und Konfigurationsstatus ohne Credentials; S/U/B |
| GET `/api/bootstrap` | `loadState`, optional `local=1` | Lokaler Basiszustand und Bereichsversionen; S/U/B/R, F06/F14 |
| GET `/api/state/events` | EventSource; Event-Cursor | SSE-Metadaten zu lokalen Änderungen/Jobs; S/U/B; keine Autorisierung aus Events ableiten |
| GET `/api/sync/jobs/{id}` | Jobstatus-/Wiederaufnahmepfad | Begrenzter dauerhafter Jobzustand; S/U; kein eigener positiver Browser-Wire-Test |
| GET `/api/sync/status` | Polling, sichtbare Tabs, Sync-Warten | Providerzustände, Versionen, Wartungsstatus; S/U/B; POST ist hier falsch |
| GET `/api/activities` | Verlauf/„Weitere Einheiten“; Tage/Limit/Cursor | Aktivitäten plus `next_cursor`; S/U; Cursorgrenzen geprüft, große Browserlisten nicht belastet |
| GET `/api/chat/history` | Chat-/Recovery-/Search-Load; Limit/Cursor/Suche | Persistierte Nachrichten plus Cursor; S/U/B/R, F06 |
| GET `/api/chat/status` | Chat-Polling | Status des anfragenden Sessionkontexts; S/U/B; interne fehlgeschlagene Command-Belege fehlen für F03 |
| GET `/api/plan` | Geplant/Heute; lokale Parameter | Kanonischer lokaler Kalender/Planstatus; S/U/B; verworfener Load F14 |
| GET `/api/weather` | Bereichs-Load; lokale Parameter | Cachezustand und Prognoseprojektion; S/U/B für Leerzustand |
| GET `/api/library` | Bibliotheksbereich; Limit/Cursor | Wiederverwendbare lokale Einträge und Cursor; S/U/B |
| GET `/api/performance` | Analyse/Leistung | Quellenmarkierte Leistungsprojektion; S/U/B |
| GET `/api/profile` | Profil-/API-Zugriff | Profil und lokale Wettbewerbsdaten; S/U/B; Auth-Fehler getestet |
| GET `/api/feedback` | Heute/Check-in-Kontext | Lokales Tages-/Aktivitätsfeedback; S/U; Browseranzeige in Basiszustand |
| GET `/api/context-preview` | Explizite Vorschau unter Mehr | Sanitiserter Coach-Kontext; S/U; keine echten Athleteninhalte abgefragt |
| GET `/api/logs` | Diagnoseansicht; Limit | Begrenzte bereinigte Logprojektion; S/U; produktiver Endpoint nicht abgerufen |
| GET `/api/diagnostics` | Diagnose-Download | Technischer minimierter Bericht; S/U; keine Live-Diagnose geöffnet |
| GET `/api/diagnostics/capture` | Capture-Status | Aktivierungs-/Ablaufstatus; S/U |
| GET `/api/privacy/export` | Expliziter Download | Begrenztes ZIP/JSONL mit Manifest, kein normales JSON-API-Objekt; S/U |
| GET `/api/privacy/delete/preview` | Löschdialog | Datenklassen, Zähler, exakter Bestätigungstext und Remote-Grenzen; S/U |
| GET `/api/change-history` | Änderungshistorie; Limit | Begrenzte sichere Diff-/Undo-Referenzen; S/U |
| GET `/api/privacy/backup` | Backup-Download | Verschlüsselte Datei, begrenztes Streaming; S/U im SQLCipher-Container |
| POST `/api/login` | Loginformular; Passwortobjekt | Session-/CSRF-Cookies bei Erfolg, keine API-Credentials; S/U/B/R, F15 |
| POST `/api/logout` | Mehr/Logout; leeres Objekt | Session widerrufen; S/U; anschließende Login-Ansicht B über 401 geprüft |
| POST `/api/privacy/restore` | Expliziter Datei-Upload | Format/Größe/Integrität/Schema prüfen, exklusiv austauschen, Sessions invalidieren; S/U; kein echter Browser-Backup-Upload |
| POST `/api/chat/cancel` | Abbrechen; `operation_id` | Nur eigene registrierte Operation abbrechen; S/U/B mit kontrolliertem Stream |
| POST `/api/transcribe` | Audio-Upload | Begrenzter unterstützter Audiotyp, `transcript`; S/U, Berechtigungsfehler B; keine echte Transkription |
| POST `/api/planning/commands` | Programmatischer Planungspfad; Kommandoobjekt | Kanonisches Planungsergebnis; S/U an Geschäftsfunktionen; kein aktiver sichtbarer Direktaufrufer im normalen UI |
| POST `/api/sync/jobs` | Explizites Job-API; Provider/Typ/Payload | 202 mit gespeichertem Job; S/U; Provider-/Typ-Validierung, Retryvertrag |
| POST `/api/sync/jobs/{id}/resolve` | Konflikt-/Jobauflösung; Strategie | Aktualisierter Job/Objektzustand; S/U, kein eigener Browser-Wire-Test |
| POST `/api/coach/actions/preview` | Spezielle Aktionsvorschau | Sessiongebundener Vorschlag und Payload-Fingerprint; S/U |
| POST `/api/change-history/undo/preview` | Änderungshistorie/Undo | Vorschau nur für gültigen aktuellen Objektzustand; S/U/R über denselben Helper |
| POST `/api/coach/actions/confirm` | Explizite Bestätigung | Einmaliges session-/payloadgebundenes Ausführungstoken; S/U |
| POST `/api/coach/actions/execute` | Freigegebene Aktion | Konkretes lokales bzw. ausdrücklich autorisiertes Remote-Ergebnis; S/U; F13 betrifft die vorher fehlende UI-Zustellung |
| POST `/api/chat/stream` | Chat; Nachricht und `client_turn_id` | `started`, `delta`, `background`, `completed` oder `error`; S/U/B/R, F03/F06/F07 |
| POST `/api/chat` | Nicht streamender/API-Chat | Turn-ID erforderlich; direkte Antwort oder 202-Hintergrundjob; S/U; kein normaler Browser-Sendepfad |
| POST `/api/sync` | Manueller Intervals-Refresh; Tage | 202 mit Operation/„läuft bereits“; S/U; Read-Sync ohne Bibliothekspush |
| POST `/api/sync/status` | Veralteter/falscher Aufrufer | Absichtlich 405 mit Verweis auf GET; S |
| POST `/api/diagnostics/capture` | Expliziter technischer Capture-Schalter | Zeitlich begrenzte Shape-/Metadaten-Erfassung; S/U; keine Aktivierung im echten Betrieb |
| POST `/api/intervals/full-resync` | Verbindungsansicht; `FULL_RESYNC` | Explizite lokale Neusynchronisierung, Provider-Gate; S/U; kein Live-Konto verändert |
| POST `/api/performance/refresh` | Leistungsansicht; leeres Objekt | Synchrones Refresh-Ergebnis/„läuft bereits“; S/U/R, F02/F04 |
| POST `/api/garmin/sync` | Verbindungsansicht; Tage | Hintergrundoperation; S/U/R an gemocktem Sync, F08/F09 |
| POST `/api/external-calendar/sync` | Kalenderverbindung | Hintergrund-Read-Refresh; S/U, letzte gute Daten bei Fehler |
| POST `/api/weather/sync` | Wetterverbindung | Erzwungener Read-Refresh; S/U, sichtbarer Fehler statt Rohprovidertext |
| POST `/api/garmin/full-resync` | Verbindungsansicht; `FULL_RESYNC` | Lokale Snapshot-Neuerstellung mit geschützten Tokens; S/U |
| POST `/api/chat/reset` | Expliziter Chat-Reset | Lokale History löschen, Remote-Conversation-Löschung separat ausweisen; S/U; Paralleljob-Szenario offen |
| POST `/api/privacy/delete` | Bestätigter Datenschutzdialog | Löschzähler und Remote-Ergebnis; S/U/R, F04 |
| POST `/api/feedback` | Check-in-Formular | Validierter lokaler Tages-Check-in; S/U; regulärer Coach-Pfad nutzt Tool |
| POST `/api/activities/{id}/feedback` | Aktivitätsfeedbackformular | Validierung/Save bzw. Löschen leerer Notizen; S/U |
| POST `/api/change-history/undo` | Freigegebener Undo-Pfad | Hashgeprüfte lokale Rücknahme; S/U; kein stiller Remote-Undo |
| PUT `/api/settings/model` | Modellauswahl; Modell-ID | Erlaubte Auswahl inklusive konfiguriertem Modell; S/U; Modellpolicy unverändert |
| PUT `/api/settings/thinking-level` | Thinking-Auswahl | Validierter persistierter Aufwand; S/U |
| PUT `/api/settings/calendar-display` | Anzeigeformular | Begrenzte vergangene/zukünftige Wochen; S/U |
| PUT `/api/athlete-context` | Kombinierter API-Vertrag; Profil/Wettkämpfe | Validierte lokale Speicherung; S/U; aktuelles Profilformular nutzt getrennten Profil-PUT |
| PUT `/api/profile` | Profilformular | Bestätigte lokale Profiländerung, danach Reload; S/U/B/R; F18 betrifft Fehlantworten |

Unbekannte `/api/*`-Pfade und nicht passende Objekt-IDs wurden im Router nachvollzogen; statische Dateien kommen aus einer Allowlist. Es gibt keinen eigenen DELETE-Handler. Das Inventar unterstellt keine zusätzlichen versteckten CRUD-Routen.

| Fehler-/Negativklasse | Tatsächlicher Nachweis | Bewertung |
|---|---|---|
| 400 / ungültige Argumente | U für JSON/Plan/Feedback; R bei 29 Einheiten und Vorlagen-Batch; B für Chat/Profile | Backend-Ursachen konkret erklärt; Chatdarstellung F07 |
| 401 / Session fehlt oder abgelaufen | U/B | Login erscheint, Appzustand wird verborgen/geleert |
| 403 / CSRF und Tool-Scope | U; R für Scope; B HTTP-Chat-403 | Grenzen greifen, F12 blockiert aber legitime Aufträge; F07 verliert Erklärung |
| 404 / Objekt oder Route fehlt | S/U an Objektpfaden; B HTTP-Chat-Injektion | Kein falsches Erfolgsobjekt aus Fehlerstatus; Chatproblem F07 |
| 409 / Konflikt oder Doppelaufruf | U für Hash/Revision/Token; R für F11; B HTTP-Injektion | Idempotenz/Revision nicht abschalten; echten Konflikt erklärbar halten |
| 413 / zu große Anfrage | U Body-/Audio-Limits; B HTTP-Injektion | Serverseitige Grenze vorhanden; Chatwiederholung verliert Entwurf |
| 415 / falscher Medientyp | U JSON-/Audio-Parser | Ablehnung vor Verarbeitung; kein separater Browser-Audio-Wire-Test |
| 422 / externe Validierung | S/U gemeinsamer Providerfehlerpfad; B HTTP-Injektion | Sichere Fehlerklassifikation; keine Behauptung einer realen aktuellen 422-Ursache |
| 429 / Rate-/Quota-Limit | U Klassifikation/Retry; B HTTP-Injektion | UI muss definitive Ablehnung von unbekanntem Ausgang trennen: F07 |
| 500/502/503/504 | U Provider-/Response-/Timeout-Grenzen; B alle vier Klassen | F03/F07 bei Seiteneffekten bzw. HTTP-Ablehnung |
| 200 mit kaputtem JSON | R/B | F18; Helper akzeptiert `{}` |
| Ungültiges SSE-/Tool-JSON, unbekanntes Tool | S/U Parse-/Dispatcher-/Cancel-Grenzen | Teilargumente dürfen keine Mutation auslösen; kein Browser-Fuzzing aller SSE-Fragmente |
| TCP-/Stream-Abbruch | U/B nach Delta | Bereits persistierte Antwort wiederhergestellt; unbekannter Ausgang vor Annahme als Regression zu F07 ergänzen |
| Veralteter Payload/erneute Bestätigung | U Hash-/Revision-/Einmaltoken-Tests | Schutz vorhanden; Frontend darf diese Fehler nicht verschweigen |

### Integrationen, Zustände und Recovery

| Integration / Zustand | Nachweis | Ergebnis / konkrete Restgrenze |
|---|---|---|
| Intervals ohne Konfiguration | S/B im isolierten Runtime | Einrichtungszustand sichtbar; keine API-Credentials im Browser |
| Intervals Startup/Daily/gewöhnlicher Pull | U mit Remote-write-Tripwires | Keine impliziten Workout-/Wettkampfwrites |
| Intervals vollständige/inkrementelle/historische Aktivitätsdaten | S/U | Seiten-/Duplikat-/Fenstergrenzen und Rohdaten-Merge geprüft |
| Intervals Leistungsrefresh bei vollständigem Snapshot | R | F02; fehlende Quelle/Fenstermetadaten |
| Intervals Auth, 400/422, 429, Netzwerk-/Serverfehler | S/U gemeinsamer HTTP-/Statuspfad | Bereinigte Fehler, letzte gute Zustände und Retryvertrag geprüft; reale Fehlantworten nicht abgerufen |
| Intervals expliziter Plan-/Bibliothekspush | S/U mit Fake-Remote | Lokale IDs/Hashes, 28er Jobteile, Updates/fehlende Remoteobjekte/Teilfehler nachvollzogen |
| Intervals expliziter Wettkampfsync | S/U | Stable-ID/Identity-Reconciliation, Tombstones und Dirty-Konflikte geprüft |
| Intervals Konflikt `keep_local`/`adopt_remote` | S/U | Lokale Strategie geprüft; eindeutige natürliche Objektauflösung mit F12 reparieren |
| Intervals Full-Resync schlägt fehl | U | Letzter Snapshot und lokale Bibliothek bleiben erhalten |
| Intervals/Garmin bereits laufender Sync | S/U | Single-Flight und Warten auf vorhandenes Ergebnis geprüft; eigener Jobstatus im Coach F12 |
| Garmin nicht konfiguriert / SDK fehlt | S/U/B für Einrichtungszustand | Sichtbarer Konfigurationsfehler; keine unsichere Login-Umgehung |
| Garmin Token-Login/MFA erforderlich | S/U an Boundary, gepinntes SDK inspiziert | Interaktiver Helper bleibt getrennt; echte MFA/Token-Erneuerung blockiert ohne Konto |
| Garmin erfolgreiche Daten-/Historical-Collection | S/U | Bounded Windows, maximal zwei parallele Range-Calls und getrennte Current-/Recovery-Abfrage |
| Garmin teilweise fehlende Quelle / Capability-Pause | S/U | Quellfehler und pausierte Capability nachvollzogen; Dictionary-Verlust gesondert F08 |
| Garmin überlappende Aktivitäten | R | F09; gefilterte Darstellung und vollständige Quelle derzeit vermischt |
| Garmin HRV-Dictionary / mehrere Fenster | S/R | F08; normgerechte Adapterfixtures fehlen |
| Garmin Body Battery morgens / optional fehlt | S/U | Getrennter Morgenpfad, datierter letzter gültiger Wert; kein pauschaler Verbindungsfehler allein wegen optionalem Wert |
| Garmin Full-Resync / fataler Providerfehler | U | Letzten guten Snapshot bei Fehler und Tokenstore-Grenze geprüft |
| Wetter ohne Standort / kalter Cache | S/U/B Leerzustand | Kein erfundener Forecast; Konfigurations-/Loadingzustand |
| Wetter Cache frisch / abgelaufen / Backoff / Force | S/U | Drei-Stunden-Cache, sichere Fehler, expliziter Force-Refresh nachvollzogen |
| Wetter für geplante Outdoor-Einheit | U | 14-Tage-Ansicht und fünf Tage Zeitvorschläge inklusive Arbeitszeiten geprüft; keine Live-Prognosegüte bewertet |
| iCalendar ungültige URL / private IP / Redirect / DNS-Rebinding | S/U | HTTPS/global-IP-Prüfung, Auflösung/Verbindung/TLS-Hostname zusammengeführt, Redirects nicht blind verfolgt |
| iCalendar ungültiger/zu großer Feed / Timeout | S/U | Größen-/Parsergrenzen, letzte gute Events bei Fehler; realer langsamer Feed nicht belastet |
| iCalendar Wiederholungen, DST, EXDATE/RDATE/Exceptions | S/U | Bounded Recurrence im achtwöchigen Fenster; keine externen Texte als Aktion |
| iCalendar benannter Refresh | S/U | Read-only; implizite remote Kalenderänderungen nicht gefunden |
| OpenAI nicht konfiguriert | B/S | Sichtbarer Einrichtungsstatus im isolierten Runtime |
| OpenAI Intent ungültig / unbekannt / hypothetisch | U | Ein begrenzter Wiederholungsversuch, dann nicht mutierende Rückfrage; echte Klassifikationsquote unbekannt |
| OpenAI Conversation-Lock / invalid conversation | U | Strukturierte begrenzte Wiederholung/Rotation vor Tools geprüft |
| OpenAI incomplete/failed/Timeout/Cancel/Background-Restart | S/U | Statusprüfung und begrenzter Lifecycle vorhanden; F03 bei erfolgreichem Write vor Folgefehler |
| GitHub Release-Check verfügbar / Fehler / Cache | S | Nur sichere Release-Metadaten, Token serverseitig; realer Release-/Tagstand nicht online verifiziert |
| Gleichzeitige Providerarbeit und Privacy-Löschung | R | F04; alter Worker trägt Daten nach Erfolg wieder ein |

**Benannte Sync-Aufträge:** Intervals, Garmin, Wetter und externer Kalender laufen über erlaubte Read-Refresh-Ziele; Leistungsrefresh hat einen eigenen Jobtyp. Lokaler Plan/Bibliothek und Wettkämpfe erhalten separate explizite Intervals-Push-Jobs. Eine erfolgreiche Queue-Annahme belegt noch keinen erfolgreichen Providerabschluss. Insbesondere „aktualisieren und anschließend anhand der aktuellen Daten bewerten“ braucht einen geprüften Abschluss-/Kontextpfad; F12 verhindert derzeit das Lesen neu erzeugter Jobs durch das zugehörige Coach-Tool. Dies wurde nicht durch echte Modellantworten überspielt.

### UI/UX und vollständige Nutzerabläufe nach Viewport

Browser: Chromium aus `mcr.microsoft.com/playwright:v1.62.1-noble`; Projekte aus der unveränderten `playwright.config.cjs`. Mobile-Projekte emulieren Pixel-5-Eigenschaften. Desktop/Tablet benutzen Desktop-Chromium. Es waren emulierte Viewports und Browser-Eingaben, keine physischen Android-/iOS-Geräte oder Bildschirmleser.

| Ablauf / Interaktion | 320×568 | 390×844 | 768×1024 | 844×390 | 1440×1000 |
|---|---|---|---|---|---|
| Anmelden → App; unauthentifizierte Ansicht | B | B | B | B | B |
| Haupt-/Unterseiten, Deep Links, Zurück, unbekannte Route | B | B | B | B | B |
| Tastaturnavigation, Fokusziel, sichtbare Labels | B | B | B | B | B |
| Touchziel-/Overflowprüfung der vorhandenen Suite | B | B | B | B | B |
| 200%-Schrift / Reduced Motion im geprüften Coach-Ablauf | B | B | B | B | B |
| Entwurf → Enter-Senden; Shift+Enter-Zeilenumbruch | B | B | B | B | B |
| Laufender Turn → FIFO-Nachricht → priorisiertes Steuern → Abschluss | B | B | B | B | B |
| Abbrechen nach weiteren Antworten | B, nach Composer-Sprung | B, nach Composer-Sprung | B | B | B |
| Lange gestreamte Markdown-Antwort → Navigation → Abschluss/History | B | B | B | B | B |
| Netzabbruch nach Delta → persistierte Antwort wieder sichtbar | B | B | B | B | B |
| Alte History nach neuem Senden/Abschluss | F06 | F06 | F06 | F06 | F06 |
| Chat-HTTP-Fehler → Entwurf/Fehlermeldung | F07 | F07 | F07 | F07 | F07 |
| Profil bearbeiten → Validierungsfehler → Entwurf behalten | B | B | B | B | B |
| Profil speichern → Seite neu laden → gespeicherter Wert | B | B | B | B | B |
| Session-401 → Login; private Ansicht verborgen | B | B | B | B | B |
| Mikrofon verweigert → Fehlermeldung; vorhandener Entwurf bleibt | B | B | B | B | B |
| Notifications verweigert → sichtbarer blockierter Status | B | B | B | B | B |
| Service Worker aktiviert; kein `/api/`-Eintrag im Cache | B | B | B | B | B |
| Gefüllter Kalender/Bibliothek/Heute/Verlauf/Leistungsansicht | B + S/U | B + S/U | B + S/U | B + S/U | B + S/U |
| axe WCAG-A/AA-Tags für die geprüften Kernansichten, leer und gefüllt | B | B | B | B | B |
| Neues Coach-Training behält angeforderte Sportart | F01, Backend + visuell | F01, globaler Backendpfad | F01, globaler Backendpfad | F01, globaler Backendpfad | F01, Backend + visuell |
| Natürlicher Mehrwochenplan → speichern → anzeigen → remote bestätigen | F05/F01; Live-Modell blockiert | gleich | gleich | gleich | gleich |
| Wettkampf per Name ändern / Undo vollständig im Chat | F12/F13; U/R statt Live-Modell | gleich | gleich | gleich | gleich |

„Gefüllt“ verwendet eine synthetische SQLCipher-Datenbank mit drei geplanten Einheiten, drei Vorlagen, Tages-Check-in, abgeschlossener Aktivität und zukünftigem Wettkampf. Die entsprechenden Ansichten wurden real aus der lokalen Anwendung geladen. F01 wurde beim Betrachten dieser Kalender-Screenshots erkannt: Die Layout-/Accessibility-Assertions prüften keine Sportidentität und blieben grün. Mobile- und Desktop-Kalender wurden zusätzlich visuell angesehen.

**Mobile Beobachtung ohne zusätzlichen Defektbeweis:** Der Composer inklusive Abbruchknopf wird beim Lesen oberhalb des unteren Seitenrands ausgeblendet. Der sichtbare Sprungknopf bringt ihn zurück; der Abbruch funktioniert danach. Zwei erste mobile Journey-Läufe warteten vergeblich direkt auf den inzwischen ausgeblendeten Abbruchknopf. Die Wiederholung mit diesem vorhandenen Bedienweg bestand. Für die Bedienbarkeit lohnt ein separat erreichbarer Abbruch/Status während laufender Arbeit; die Beobachtung wird nicht als weiterer harter Fehler gezählt.

| Nicht vollständig ausgeführter Nutzerablauf | Konkreter Grund / erforderlicher nächster Nachweis |
|---|---|
| Echter natürlichsprachlicher Auftrag → Intent-Modell → alle 27 Tools → abschließender Coach-Text | Kein echter OpenAI-Aufruf im Review; eine freigegebene synthetische Account-/Responses-Testumgebung mit erwarteten Tool-/Wirkungsbelegen ist erforderlich |
| Benannter Garmin-/Intervals-Sync → reales Providerergebnis → anschließende Coach-Bewertung | Keine echten Credentials/Tokens oder Kontoänderungen; Provider-Contract-Fixtures und später ein kontrollierter Accountlauf erforderlich |
| Adaptive Vorschau → Freigabe nach Mitternacht/Profil-Zeitzonenwechsel | Statisch geprüft, keine Uhr-/Browser-Wiederaufnahmeprobe; veraltete Vorschau mit neuer lokaler Tagesgrenze gezielt prüfen |
| Physische mobile Tastatur, Rotation bei geöffneter Tastatur, IME, Voice-Aufnahme und echter Transkriptionsrücklauf | Kein physisches Gerät/Mikrofon und keine echte Transkriptions-API; Berechtigungsverweigerung und Draft-Verhalten sind geprüft |
| Frische PWA-Installation → aktueller Asset-Cache → Schließen → Offline-Rückkehr mit demselben Build | Kompletter Installations-/Offline-Roundtrip auf einem physischen Gerät fehlt; keine zweite App-Version oder alter Cache als Voraussetzung |
| Background-/OS-Notification bis zum gesperrten Gerät und Click-Ziel | Keine reale OS-Push-/Gerätesitzung; Quellpfad und Browser-Permission-Fallback geprüft |
| Privacy-Export/Backup-Download → Browser-Upload Restore → neue Anmeldung | Export-/Restorefunktionen und verschlüsselte Dateien nur in isolierten Unit-Tests; kompletter binärer Browser-Roundtrip mit einem frisch erzeugten Backup desselben Builds nicht ausgeführt |
| Gleichzeitige echte Tabs / Sessionwechsel mit alten Responses | Ein-Browser-Page-Fixtures pro Test; hierfür separate gehaltene Requests und Tab-/Lease-Barrieren erforderlich |

## Validierung und Beleginventar

| Prüfung | Ergebnis | Aussagegrenze |
|---|---|---|
| `python -m unittest discover -s tests -v` auf Windows/Python 3.13 | **423 Tests, 39,627 s, OK; 3 übersprungen** | Die drei SQLCipher-spezifischen Tests benötigen die Containerbibliothek |
| `python -m py_compile server.py tests/test_server.py` | **Bestanden** | Syntax, keine Vollabdeckung aller Verhaltenspfade |
| `docker build -t ai-coach:review-20260905 .` im Review-Worktree | **Bestanden** | Separates Image; kein Austausch einer laufenden Anwendung |
| Discovery im isolierten Python-3.14-Container, kein Netzwerk | **423 Tests, 5,665 s, OK; keine Skips** | Enthält die drei SQLCipher-Checks; allgemeine Tests verwenden weiterhin ihre schnellen temporären Fixtures |
| Gepinnte Garmin-Clientmethoden und Signaturen im Image | **Inspiziert** | Keine Live-Schema-/Verfügbarkeitsgarantie; F08 betrifft die unterstützte Dictionary-Form |
| Vorhandene Playwright-Suite im geeigneten internen Netz | **20/20 bestanden**, vier Fälle je Viewport | Aktuelle Chromium-/Fixtureumgebung; keine Aussage über alle Geräte |
| Zusätzliche Browser-Journeys | **25/25 nach Korrektur des mobilen Bedienwegs bestanden** | Queue/Steering/Cancel, Netzwerk-Recovery, Permission-Fallbacks, Profil/401 und Cache; erste zwei mobile Timeouts transparent oben dokumentiert |
| Zusätzlich gefüllte Ansichten | **5/5 Layout-/Accessibility-Fälle bestanden** | Visuelle Prüfung fand trotzdem F01; fachliche Sportidentität war keine ursprüngliche Assertion |
| Zusätzliche Browser-Defektprobes | **25/25 erwartete Fehlerzustände reproduziert** | F06 zweimal, F07, F14 und F18 je Viewport; F07 enthält elf HTTP-Statusvarianten |
| Zusätzliche Backend-Defektprobes | **13 Probe-Szenarien reproduziert** | Temporäre DB/gemockte Grenzen; Sportprobe enthält vier verschiedene Eingabesportarten |
| Vollständiger neuer Ruff-/Mypy-/Coverage-Lauf über die Anwendung | **Nicht ausgeführt** | Review ist quellen- und verhaltensbasiert; der vorhandene CI-Quality-Pfad deckt ohnehin nur einen begrenzten Einstieg ab |
| Aktueller CVE-/Supply-Chain-/Lizenzabgleich | **Nicht ausgeführt** | Keine aktuellen Sicherheits-/Lizenzfreigaben aus Lockfile-Pinning ableiten |
| Echte LAN-/VPN-/HTTPS-Instanz und reale Konten | **Nicht abgefragt** | Kein produktiver Athletenzustand untersucht; im lokalen Docker-Daemon lief zu Beginn keine Anwendungsinstanz, deshalb eigener isolierter Runtime |

Insgesamt sind dies **75 logische Browser-Prüffälle über fünf Viewports: 50 Verhaltens-/Darstellungsfälle und 25 Defektprobes**. Wiederholungen zur Klärung des Testaufbaus werden nicht als zusätzliche Abdeckung gezählt. Der erste Lauf im komplett abgeschalteten Docker-Netz hatte 15 erfolgreiche und fünf fehlgeschlagene vorhandene Browserfälle: Chromium meldete dort `navigator.onLine = false`, weshalb die App ihr Recovery-Polling absichtlich pausierte. Nach Wechsel auf ein internes Netz ohne externen Zugriff bestand die unveränderte vorhandene Suite. Diese fünf Fehlschläge sind kein Anwendungsfinding.

Die allgemeine Testkonfiguration und das echte Login/SQLCipher-Startup blieben wirksam. Ein ausschließlich synthetisches Entwicklungspasswort wurde nur für die Fixture verwendet und wird hier nicht wiedergegeben. Externe Transporte waren gemockt/gesperrt; Fixture-Runtimes erhielten weder `.env` noch einen Live-Datenmount. Temporäre Browser-Authdateien, Cookies und Trace-Header wurden nicht als Reviewbelege geöffnet oder in dieses Dokument übernommen.

Runtime-Identitäten: `ai-coach-review-20260905` (`00fd51d8d58d`, vollständig abgeschaltetes Netz), `ai-coach-review-online-20260905` (`4bf520b7fee3`, internes Netz), die frischen `ai-coach-review-matrix-<projekt>-20260905` und `ai-coach-review-journey-<projekt>-20260905` sowie `ai-coach-review-seeded-20260905` (`5326daa5387e`, gefüllte Datenbank). Das interne Netz hieß `coach-review-20260905`. Alle wurden ausschließlich für diesen Review angelegt und anschließend entfernt.

Die lokal erzeugten Prüfdateien liegen unter `%TEMP%/coach-review-20260905/`: `native-tests.txt`, `container-tests.txt`, `backend-probes.txt`, `backend_probes.py`, `browser-matrix-*.txt`, `browser-journey-*.txt`, `browser-cancel-*.txt`, `browser-populated.txt` sowie die synthetischen Testskripte. Sie sind Hilfsbelege außerhalb des Git-Artefakts und können vom Betriebssystem später entfernt werden. Der Bericht enthält daher die wesentlichen Eingaben, Ergebnisse und Abnahmekriterien selbst.

| Probe | Kontrollierte Störung / Eingabe | Beobachtetes Ergebnis | Finding |
|---|---|---|---|
| `coach-plan-sport-preservation` | Stage/Commit mit Run, Kraft, VirtualRide, Swim | Alle vier als Ride gespeichert und im vorbereiteten Event-Payload | F01 |
| `performance-refresh-preservation` | Snapshot mit Rohdaten/Fenster, gemockter Performance-Refresh | Beide Felder im neuen Snapshot weg | F02 |
| `effect-before-followup-failure` | Check-in-Write, dann Responses-503 | Write/Beleg vorhanden, Assistant-Nachricht fehlt | F03 |
| `privacy-delete-active-writer` | Refresh vor Commit halten, löschen, Refresh freigeben | Nach erfolgreicher Löschung wieder eine Aktivität | F04 |
| `29-unit-plan` | 29 valide datierte Einheiten | Staging ja, Commit 400, 0 Einheiten | F05 |
| Browser: alte History / neue Nutzer-Bubble | Alte leere History nach Senden | Nutzer-Bubble verschwindet | F06 |
| Browser: alte History / neuer Abschluss | Completion vor alter History; dreifach pro Viewport | Assistant-Bubble wird wieder entfernt | F06 |
| Browser: HTTP-Ablehnungen | 400/403/404/409/413/422/429/500/502/503/504 | Entwurf und konkrete Fehlermeldung fehlen | F07 |
| `hrv-dictionary-merge` | Ein HRV-Dictionary mit Record | Leere Ergebnisliste | F08 |
| `garmin-raw-deduplication` | Garmin-Aktivität mit zusätzlichem Feld und Intervals-Match | Keine Aktivität/kein Zusatzfeld im Snapshot | F09 |
| `template-batch-late-error` | Gültige, dann unzulässig datierte Vorlage | 400 und trotzdem eine gespeicherte Vorlage | F10 |
| `two-same-kind-actions` | Zwei verschiedene Check-in-Tage | Zweiter Aufruf als Duplikat abgelehnt | F11 |
| `named-competition-scope` | Vorhandener synthetischer Wettkampf, lokaler Wettbewerbsscope | 403 vor Update | F12 |
| `created-job-scope` | Autorisierten Refresh enqueuen, neue Job-ID lesen | 403 trotz eigener erzeugter Job-ID | F12 |
| `undo-action-delivery` | Lokale Änderung, dann strukturiertes Undo | Vorschlag verschachtelt ja, UI-Aktionsliste leer | F13 |
| Browser: andere Bereiche während Load | Chat-History halten, Plan/Bibliothek anfordern | Kein Plan-GET | F14 |
| `unicode-login` | Zulässiges synthetisches Unicode-Passwort | TypeError | F15 |
| Workflow-Ref-Vergleich | Dispatch mit abweichendem Event-SHA/Tag | Tests, Version und Build sind an den Event-SHA gebunden; ein `source_ref`-Override ist entfernt | F16 |
| Browser: kaputte 200-Antwort | Ungültiges JSON beim PUT | API-Helper liefert `{}` als Erfolg | F18 |
| Test-Loader-Inventar | Discovery-Menge versus Shard-Loader | 13 Modul-Tests nicht im Runner | F17 |

## Ohne weiteren belegten Defekt geprüfte Grenzen

- SQLCipher-Start verweigert die unsichere Produktionsvariante ohne Verschlüsselungsunterstützung. Das Review hat keinen Fallback in die Anwendung eingebaut.
- Session-/CSRF-Prüfungen, festes Ablaufdatum, Cookie-Härtung, Raten-/Body-Limits und statische Datei-Allowlist sind im geprüften Code und den einschlägigen Tests vorhanden. F15 betrifft den Passwortvergleich, keine absichtliche Auth-Umgehung.
- Kalenderfeeds werden nicht wie beliebige URLs über einen ungeprüften Redirectpfad geladen. Globale Zieladressen, TLS-Hostname, begrenzter Feed und Parser werden geprüft; letzte gute Kalenderdaten bleiben bei Parser-/Providerfehlern erhalten.
- Gewöhnliche Startup-/Daily-/Aktivitäts-Syncs haben getestete Read-only-Verträge. Remote-Plan-, Bibliotheks-, Wettbewerbs- und SICK-Writes haben explizite eigene Aktionspfade.
- Der vorhandene Change-Batch hat einen getesteten Rollback. Adaptive Freigaben prüfen Fingerprints und Wiederholung; Einmaltoken sind session- und payloadgebunden. Dies ersetzt nicht die separaten F10-/F13-Fixes.
- HTML/Markdown wird vor der Darstellung escaped; Linkschemata sind begrenzt. Die injizierte HTML-/JavaScript-Payload führte im Browser keinen Code aus.
- PWA-Assets und Cacheversion stimmen für den Snapshot überein. Private API-Antworten wurden im geprüften Service-Worker-Cache nicht gefunden.
- Backup-/Restorevalidierung, Wartungs-Drain, Recoverykopie, Sessioninvalidierung und begrenztes Datei-/ZIP-Streaming wurden durch die dafür vorhandenen isolierten Tests geprüft.

## Querschnittliche Aufgaben und verbleibende Unsicherheit

Diese Punkte sind keine zusätzlichen bestätigten Produktfehler und sind nicht in den 18 Findings enthalten:

- [x] **Q01 – Fachliche Browserassertions ergänzen:** Die gefüllte Ansicht kann axe und Overflowprüfungen bestehen und trotzdem die falsche Sportart zeigen. Je Kernfähigkeit nicht nur Sichtbarkeit, sondern erwartete lokale ID, Sport, Datum, Quellenlabel und tatsächlichen Speicher-/Syncstatus prüfen. Der bestehende Login-axe-Schritt beginnt außerdem mit authentifizierter Storage-State; ein versteckter Login-Dialog ist kein vollständiger Login-Accessibility-Nachweis.
- [x] **Q02 – Einen gemeinsamen Operationsvertrag etablieren:** Über Tool-Ergebnis, HTTP, SSE, History und Job-Status dieselben Turn-/Objekt-/Resultatfelder verwenden. Das adressiert die konkreten Brüche F03/F07/F12/F13. Nach N02 existiert genau ein kanonischer Coach-Pfad; keine Legacy-Regeln oder Kompatibilitätsadapter bleiben daneben bestehen.
- [x] **Q03 – Mobile laufende Aktionen sichtbar halten:** Den Abbruch-/Fortschrittsbereich beim Lesen langer Antworten unabhängig vom verborgenen Composer bewerten. Der aktuelle Umweg ist ausführbar, kostet aber einen zusätzlichen gezielten Tap.
- [x] **Q04 – Verbliebene deterministische Race-Tests ergänzen:** Zwei Tabs/Leasewechsel, Reset mit queued/running Job, verspätete Antwort einer abgemeldeten Session nach erneutem Login, Adaptive-Apply nach Tageswechsel und Garbage-Collection abgelaufener Artefakte separat mit Barrieren prüfen. Alle Daten und Vorgänge stammen aus derselben aktuellen Anwendungsversion. Diese Szenarien wurden nicht als grün deklariert.
- [x] **Q05 – Erhalt letzter guter Garmin-Teilquellen prüfen:** Für jede aktuelle Metrik und jeden Backfill-Cursor eine Quelle ausfallen lassen; nur erfolgreich gespeicherte Fenster dürfen als vollständig gelten. Die bestätigten Format-/Originaldatenverluste sind F08/F09; weitergehende Verluste sind hier ein gezielter Prüfauftrag.
- [x] **Q06 – Moderne Modulgrenzen auf die Fehlerschwerpunkte ausrichten:** Zustandszusammenführung und Operationsbelege zuerst kapseln; reine Aufteilung von `server.py`/`app.js` behebt die nachgewiesenen Races und Transaktionsgrenzen nicht.
- [ ] **Q07 – Vor einer Betriebsfreigabe offene Laufzeitnachweise schließen:** Freigegebene Provider-/Responses-Testumgebung, reale HTTPS-/Geräteprüfung, aktueller Dependency-Scan und ein Publish-Dispatch ohne Veröffentlichung. Dazu ist kein Lesen von produktiven Geheimnissen in Chat/Logs erforderlich.

Die Prüfung bewertet den dokumentierten Quellstand und eine isolierte lokale Ausführung. Sie bescheinigt weder die Fehlerfreiheit eines konkreten Athletenkontos noch medizinische Eignung, aktuelle Providerverfügbarkeit, Branchschutz oder den Zustand einer installierten PWA. Die Coach-first-Freigabe bleibt wegen der bestätigten Kernfehler und der ausdrücklich benannten offenen End-to-End-Nachweise aus.

**Abschluss des Review-Auftrags:** Complete for the recorded source snapshot; all checklist domains were reviewed or explicitly blocked.
