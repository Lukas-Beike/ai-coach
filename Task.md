# Feature- und Bug-Review: Umsetzungsplan

Stand: 2026-08-31  
Basis: `develop` / `45b5ca3`

## Arbeitsregeln

- Jedes Workitem erhält einen eigenen Branch aus dem aktuellen `develop`.
- Vor Beginn und unmittelbar vor dem PR wird der Branch auf `develop` rebased.
- Pro Workitem: implementieren, Tests ergänzen/ausführen, Conventional Commit,
  PR eröffnen, Squash-Auto-Merge aktivieren und Merge-/Check-Status prüfen.
- Erst nach bestätigtem Auto-Merge wird das nächste Workitem begonnen.
- Keine Secrets, echten Datenbanken, Garmin-Tokens oder Root-`.env`-Werte in
  Tests, Logs, Commits oder PRs.

## Workitems

### W0 – Task-Tracking

- [x] `Task.md` anlegen und in einem eigenen Branch committen/mergen.

### W1 – Sichere Provider-Resyncs

- [x] Voll-Resync lädt und validiert neue Daten vor dem Ersetzen.
- [x] Letzte gute Snapshots bleiben bei Fehlern erhalten.
- [x] Lokale Wettbewerbe und Sync-Tombstones bleiben autoritativ erhalten.
- [x] Garmin-Snapshot bleibt bei fehlgeschlagenem Voll-Resync erhalten.
- [x] Regressionstests für Erfolg, Fehler und lokale Datensätze ergänzen.

### W2 – Transaktionssicheres Backup und Restore

- [x] Konsistenten Datenbank-Snapshot erstellen.
- [x] Restore gegen vollständiges aktuelles Schema, Migrationen und Integrität prüfen.
- [x] Restore-Sessions invalidieren und erneute Anmeldung erzwingen.
- [x] Regressionstests für unvollständige, beschädigte und gültige Backups ergänzen.

### W3 – Sichere Remote-Kalenderaktionen

- [x] Löschen ausschließlich für zukünftige, app-eigene Workout-Events erlauben.
- [x] Rennen, Wettbewerbe und fremde Remote-Events serverseitig schützen.
- [x] UI nur mit zulässigen Löschaktionen versehen.
- [x] Tests für Kategorien, External-IDs und nicht erlaubte Events ergänzen.

### W4 – Coach-Mutationen und Morgen-Check-in absichern

- [x] Automatischer Morgen-Check-in bleibt vollständig read-only.
- [x] Library-, Plan- und Activity-Feedback-Mutationen benötigen eine explizite
  aktuelle Nutzeraktion/Bestätigung.
- [x] Prompt-Injection- und Halluzinationsfälle dürfen keine dauerhaften
  Mutationen auslösen.

### W5 – Kanonische lokale Planung

- [x] Lokale und Remote-geplante Einheiten in einem kanonischen Read-Model vereinen.
- [x] Kalender, Compliance, Wochenübersicht, Wetter und Konflikte verwenden dieselbe Sicht.
- [x] Sync-Quelle, lokale ID, Remote-ID und Sync-Status sichtbar machen.
- [x] Lokale Einheiten im Kalender bearbeiten/löschen/verschieben können.

### W6 – Adaptive Planung mit Concurrency-Schutz

- [x] Preview speichert Version/Hash der betroffenen Einheit.
- [x] Apply lehnt veraltete Previews ab und überschreibt keine späteren Änderungen.
- [x] Fehlende Ziele werden als stale/partial gemeldet, nicht als erfolgreich angewendet.
- [x] Preview-/Apply- und Wiederholungs-Tests ergänzen.
- [x] Mutationen gegen doppelte Tool-Aufrufe idempotent machen.

### W7 – Check-in, Datum und Zeitzonen

- [x] Vollständige Check-in-PWA-Oberfläche mit Verlauf und Bearbeitung ergänzen.
- [x] Serverweite lokale Datumsfunktion anhand der Profil-Zeitzone verwenden.
- [x] Frontend behandelt Datum-only-Werte ohne UTC-Verschiebung.
- [x] Regeln für heutige, zukünftige und vergangene Trainingsdaten vereinheitlichen.
- [x] Zeitzonenvalidierung beim Profil speichern.

### W8 – Provider- und Kalender-Sync-Robustheit

- [x] `remote_missing` tatsächlich automatisch reconciliieren/wiederherstellen.
- [x] iCalendar-Feeds strikt validieren und letzten guten Stand behalten.
- [x] Wiederkehrende iCalendar-Termine mit begrenzter Expansion unterstützen oder klar ablehnen.
- [x] Kalender-SSRF/DNS-Rebinding-Schutz vervollständigen.
- [x] Intervals-/Garmin-Aktivitäten paginieren und Teilstände transparent machen.

### W9 – Wettbewerbs- und Konfliktauflösung

- [x] Identity-only-Matches dürfen lokale Änderungen nicht still verwerfen.
- [x] Konfliktstatus und klare Merge-/Adopt-Strategie ergänzen.
- [x] Wettbewerbs- und Kalenderkonflikte mit Zeitfenstern statt nur Datum bewerten,
  sofern die Providerdaten das zulassen.

### W10 – Chat-, Kosten- und Statuszuverlässigkeit

- [x] Provider-Lock-Retry anhand strukturierter Fehlergründe reparieren.
- [x] Responses-Fehlerstatus strikt validieren.
- [x] Tool-Mutationen und Follow-up-Requests idempotent/reconciliierbar machen.
- [x] Chat-Warteschlange begrenzen/abbrechbar machen und Kostenbudget vorsehen.
- [x] Usage-Zähler atomar und zur lokalen Tagesgrenze passend aktualisieren.
- [x] Garmin-Fehlerstatus zuverlässig persistieren.

### W11 – Bibliothek, Kalenderhorizont und PWA-Produktlücken

- [x] Library- und Mehrwochenplan-Ansicht vollständig nutzbar machen.
- [x] Lifecycle für lokale Einheiten (editieren, archivieren, löschen, verschieben)
  ergänzen.
- [x] Kalenderhorizont mit tatsächlich geladenem Providerfenster synchronisieren.
- [x] Unbenutzte Public-Calendar-Importreste entfernen oder vollständig anbinden.
- [x] Open-Meteo-Attribution sichtbar und korrekt darstellen.

### W12 – Datenschutz, Security-Polish, Tests und Dokumentation

- [x] Datenschutzexport vollständig definieren und implementieren.
- [x] Ergebnis eines fehlgeschlagenen Remote-Löschens in der UI sichtbar machen.
- [x] Cookies für HTTPS-Deployment härten.
- [x] Wetter-Fehler mit Backoff/negativem Cache behandeln.
- [x] Native Tests von Root-`.env` entkoppeln, ohne SQLCipher-Schutz abzuschwächen.
- [x] Frontend-/Browser-Smoke-Checks und fehlende Zustandsübergangstests ergänzen.
- [x] README, API-Verhalten und Release-/Asset-Versionen aktualisieren.

## Abschlusskriterien

- [x] Alle Workitems sind implementiert, getestet und jeweils per PR gesquasht gemerged.
- [x] `python -m unittest discover -s tests -v` im vorgesehenen Docker-Testlauf erfolgreich.
- [x] `python -m py_compile server.py tests/test_server.py` erfolgreich.
- [x] Relevanter Docker-Build erfolgreich.
- [x] Browser-Smoke-Checks für Login, Planung, Check-in, PWA-Assets und Notifications durchgeführt.
- [x] Arbeitsbaum enthält keine unbeabsichtigten Änderungen oder Runtime-Dateien.
