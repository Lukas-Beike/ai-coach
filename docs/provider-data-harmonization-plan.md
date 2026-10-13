# Plan: Providerunabhängiges Datenformat für Trainings- und Gesundheitsdaten

Stand: 10. Oktober 2026. Grundlage ist Commit `44c90499` auf `develop`
(`APP_VERSION` 1.12.27, veröffentlicht mit Schema v4 und eingefroren als
`tests/fixtures/schema_v4.sql.txt`; `develop` steht bereits auf
`CURRENT_SCHEMA_VERSION = 5` mit `nutrition_logs.logged_time_known`). Die
kanonische Persistenz dieses Plans wird damit **Schema v6**. Status
(11. Oktober 2026): Welle 1 (Phase 0, kanonisches Paket, Guard) und Welle 2
(Mapper, Sport-Klassifizierer, Provider-Register) und Welle 3 (Phase 2,
kanonische Leseschicht ohne Verbraucher) sind gemergt; Welle 4 ist der nächste
Schritt, siehe Abschnitte 5.1 und 5.5.

Ziel: Daten von Intervals.icu, Garmin Connect und künftigen Providern wie Wahoo
werden an genau einer Grenze in ein eigenes, versioniertes, kanonisches Format
übersetzt. Fachlogik, HTTP-API, PWA und Coach arbeiten ausschließlich mit diesem
Format. Ein neuer Provider besteht danach aus Adapter, Mapper, Deskriptor,
Verdrahtung, Konfiguration und Tests – ohne Änderungen in `performance/`,
`activities/`, `planning/`, `coach/`, `http_api/` oder `public/`.

Der Plan setzt die Empfehlung A1 aus
`docs/reviews/2026-09-27-architecture-coach-review-gpt-6-luna.md` (Roh-,
normalisierte, persistierte und öffentliche Verträge trennen) für Providerdaten
um. Er beauftragt keine Veröffentlichung, keine Umstellung einer bestehenden
Installation und keine Remote-Schreibvorgänge.

## 1. Geprüfte Ausgangslage

### 1.1 Befund

| Bereich | Heute | Folge |
| --- | --- | --- |
| Intervals inbound | `IntervalsSnapshotReader` lädt Aktivitäten, Wellness, Events und Athletenwerte. `backend/planning/context.py` filtert Felder (`ACTIVITY_FIELDS`, `WELLNESS_FIELDS`, `EVENT_FIELDS`), benennt aber nicht um. Gespeichert wird ein JSON-Blob in `snapshots.payload` mit kompakter Liste, unbegrenztem `raw_provider_data` und bis zu 12 Vollkopien. | Intervals-Feldnamen (`icu_training_load`, `start_date_local`, `moving_time`, `ctl`/`ctLoad` …) laufen bis in `performance/`, `activities/`, `coach/`, `http_api/` und `public/*.js`. |
| Garmin inbound | `collect_garmin_data` liefert Roh-JSON je Quelle; gespeichert als kv-Eintrag `garmin_snapshot`. Jeder Verbraucher normalisiert beim Lesen selbst; Helfer wie `_first_present`, `_as_number` und `_garmin_key` existieren in rund acht Kopien mit abweichenden Feldlisten. Mehrere Module lesen den kv-Eintrag direkt. | Schemaänderungen bei Garmin wirken still und an vielen Stellen gleichzeitig. |
| Identität und Dubletten | Aktivitäts-ID ist die Provider-ID. Der Garmin↔Intervals-Abgleich läuft heuristisch zur Laufzeit (Start ±30 min, Dauer-/Distanztoleranz); gespeicherte `activity_matches` veralten und werden nur in Tests gelesen. Die Aktivitätsliste (`activities/read_service.py`) zeigt nur Intervals-Aktivitäten aus `recent_activities`. `"wahoo"` ist bereits ein Herkunftswert innerhalb von Intervals-Daten (`backend/activities/identity.py:60-61`). | Keine stabile, providerübergreifende Einheit; ein dritter Provider vervielfacht Dubletten. |
| Gespeicherte Aktivitätsreferenzen | Die Provider-ID ist dauerhaft gespeichert: als Primärschlüssel von `activity_feedback`, im Detailcache `activity_detail:<sha256(id)>`, in `equipment_assignment:<id>` (`athlete/equipment.py:245`), in Aufträgen `activity_details` in `sync_jobs` (`sync/jobs.py:246`), im HTTP-Paginierungscursor `(start_date_local, id)` (`activities/read_service.py:31-36`) und als Werkzeugargument im Coach bzw. im OpenAI-Gesprächsverlauf. Gespeicherte Detailanalysen gelten nur, solange `summary_sha256` über die unveränderte Aktivitätszeile passt (`performance/report_service.py:63-64`). | Neue IDs oder eine veränderte Zeilenform machen Feedback, Ausrüstungszuordnung und Analysen unauffindbar. Alte Cursor und IDs im Gesprächsverlauf müssen dauerhaft auflösbar bleiben. |
| Schreib- und Löschsemantik | Inkrementelle Intervals-Syncs führen neue und vorhandene Datensätze zusammen; nur ein vollständiger Sync ersetzt sie. Remote gelöschte Aktivitäten verschwinden deshalb nur bei vollständigen Syncs. `recent_activities` wird auf 500 Einträge gekürzt, `raw_provider_data` nicht. Snapshot, Planimport, Markierung, Bibliothek, Cursor und Fensterwerte werden in getrennten Transaktionen geschrieben (`sync/intervals.py:257-370`), der Cursor zuletzt. Garmin setzt Cursor nur bei vollständigem Abruf (`sync/garmin.py:501`). Der `historical`-Cursor steuert die Wiederaufnahme des historischen Backfills (`sync/scheduler.py:304`). | Eine dauerhafte Tabelle braucht eine explizite Löschregel. Ein Dual-Write in einer eigenen Transaktion nach dem Cursor könnte Lücken hinterlassen, die nie nachgeladen werden. |
| Sportarten | Mehr als acht getrennte Klassifizierer, u. a. in `activities/identity.py`, `performance/activity_validation.py`, `planning/workouts.py`, `planning/competitions.py`, `public/analysis.js` und `public/performance-view.js`. Lokale Ausrüstung speichert die Sportart im Intervals-Vokabular (`Ride`, `VirtualRide`, `Run` …, `athlete/equipment.py:529`), ebenso Bibliothek und Planeinheiten. | Uneinheitliche Zuordnung und Fehltreffer, etwa durch den Substring „rad“. Gespeicherte Athletendaten enthalten Provider-Vokabular. |
| Quellenlabels | Anzeige-Strings wie „Intervals.icu“ und „Garmin Connect“ dienen als Schlüssel; Backend (`performance/context.py`) und Frontend (`startsWith("Intervals.icu")`) verzweigen darauf. | Eine Umbenennung oder ein neuer Provider bricht Logik still. |
| Präzedenz | Verteilt auf `current_metrics.py`, `recovery_context.py`, `planning_recovery.py`, `body.py`, `chart_history.py`, `training_focus.py` und `activities/duplicates.py`. | Nicht als Ganzes prüfbar; ein neuer Provider erfordert Änderungen in allen Modulen. |
| Orchestrierung | Kein Provider-Register. Providernamen stehen in festen Mengen und if/elif-Ketten: Sync-Kern (13 Dateien), HTTP (≈5), Coach (≈8), Frontend (4–5), Konfiguration, Diagnose und Datenschutz. | Ein dritter Provider berührt rund 30 Dateien. |
| Outbound | Das lokale Planformat ist faktisch ein Intervals-Event: Sportvokabular `INTERVALS_WORKOUT_TYPES`, Workout-Text in `description`, nach dem Sync zurückkopierte `icu_*`/`workout_doc`-Felder. Remote-IDs liegen in Einzel-Slots (`external_id`, `remote_event_id`, `competitions.intervals_event_id`); `sync/planned_calendar.py` ruft REST-Endpunkte am Client vorbei auf. | Ein zweites Ziel, etwa Wahoo-Pläne, ist ohne Schemaänderung nicht abbildbar. |
| Persistenz | Keine normalisierten Providertabellen. Ältere Schemata werden erkannt, indem die Migration das aktuelle Schema zurückrechnet (`backend/db/migrations.py:17-44`). | Neue Tabellen erfordern einen Umbau dieser Erkennung, sonst würden bestehende Datenbanken abgewiesen. |

### 1.2 Vorhandene Bausteine

- Metrik-Hülle aus `freshness.garmin_metric_freshness`
  (`{value, unit, source, freshness, fetched_at, observed_at, measurement_status, …}`)
  als Vorlage für einen kanonischen `MetricValue`.
- Zeitreihen- und Punktformate in `performance/garmin_metric_history.py`,
  `performance/body.py` (`{date, value, observed_at, synced_at}`) und
  `performance/history.py`.
- Alias- und Einheitenhelfer in `performance/activity_validation.py`
  (Intensität, Pace) als Startpunkt der Mapper.
- Providerneutrale Job-Hülle `(provider, type)` in `sync_jobs`, das
  `SyncJobRunner`-Protokoll, Cursor `(provider, stream)` und
  `provider_refresh_history`.
- Port-Muster `ProviderSnapshotReader` in `backend/runtime/ports.py` mit
  Implementierung in `backend/sync/snapshot_reader.py`.
- Hashbasierte Push-Manifeste, Konfliktzustände und `sync/plan_repair.py`;
  `structured_steps` in `activities/workout_text.py` als providerneutrales
  Schrittmodell.

### 1.3 Nebenbefund: Intervals-HRV-Baseline bleibt leer

`performance/personal_recovery.py:44-46` verwendet Intervals-HRV nur bei
`hrv_method` `RMSSD` oder `SDNN`. Die Intervals-Wellness-API liefert dieses Feld
jedoch nicht; nur Tests und das e2e-Fixture setzen es. Intervals kodiert die
Methode stattdessen im Feldnamen: `hrv` (rMSSD) und `hrvSDNN` (SDNN; Semantik
laut Intervals-Forum bzw. Drittdokumentation, nicht aus einem offiziellen
Schema). Zusätzlich verwirft `planning/context.py:176` (`WELLNESS_FIELDS`, über
`selected(...)` in `compact_snapshot` angewandt) `hrvSDNN`, und
`performance/context.py:61` und `:124` übergeben genau diese kompakte
`recent_wellness`-Liste. Korrektur (Welle 1, Einheit 1): Methode aus dem
Feldnamen ableiten (`hrv` → `RMSSD`, `hrvSDNN` → `SDNN`, getrennte Serien),
`hrvSDNN` in `WELLNESS_FIELDS` aufnehmen, Regressionstest über
`compact_snapshot` → `current_performance_context`. Das kanonische Format behebt
diese Fehlerklasse später strukturell.

## 2. Leitprinzipien

1. **Genau eine Übersetzungsgrenze.** Wire-Formate kennt nur der jeweilige
   Provider-Mapper. Dahinter existieren keine Provider-Feldnamen.
2. **Rohdaten bleiben erhalten, kanonische Daten sind abgeleitet.** Mapper sind
   reine, versionierte Funktionen. Eine neue Mapper-Version projiziert
   gespeicherte Rohdaten ohne Netzabruf neu.
3. **Herkunft an jedem Wert:** Provider, Provider-ID, Aufzeichnungsgerät,
   Messzeit, Abrufzeit und Mapper-Version. *Provider* (woher die App Daten lädt)
   und *Herkunft* (welches Gerät aufgezeichnet hat) sind getrennte Begriffe.
4. **Präzedenz deklarativ an einer Stelle.** Startwert ist exakt das heutige
   Verhalten, festgeschrieben durch Charakterisierungstests.
5. **Lokale Autorität bleibt.** Vom Athleten bestätigte Profil-, Wettkampf-,
   Ausrüstungs- und Planwerte überschreibt keine Synchronisation.
6. **Untrusted bleibt untrusted.** Provider-Freitext wird begrenzt, nie als
   Instruktion behandelt und nur bereinigt an den Coach gegeben.
7. **Kleine explizite Typen statt Framework.** Standardbibliothek:
   `dataclass(frozen=True)`, `Enum`/`Literal`, `Protocol`. Unbekannte
   Providerfelder werden nicht durchgereicht; ein neues kanonisches Feld ist eine
   bewusste, getestete Vertragsänderung mit einem konkreten Verbraucher.
8. **Strangler statt Big Bang.** Die Schritte in dieser Reihenfolge:
   1. eine kanonische Leseschicht über den Bestandsdaten;
   2. stabile Identität und kanonische Speicherung parallel zu den Snapshots;
   3. die Umstellung der Verbraucher;
   4. zuletzt der Rückbau.

   Jeder Schritt ist ein eigener PR mit Paritätstests.
9. **Bestehende Verträge bleiben:** SQLCipher, versionierte Migrationen,
   Backup/Restore, Datenschutz-Export und -Löschung, Session/CSRF, explizite
   Remote-Freigaben, Adaptive-Preview/Apply.

## 3. Zielarchitektur

### 3.1 Schichten und Pakete

```text
Provider-API ─► backend/providers/<p>.py             Transport, Auth, Paging (wie heute)
                backend/providers/<p>_mapping.py     Wire → kanonisch (rein, versioniert)
                backend/providers/<p>_descriptor.py  Fähigkeiten, Bereiche, Label, Konfig-Prüfung
                         │
                         ▼
backend/sync/ingest.py              Roh- und kanonische Datensätze in einer Transaktion,
                                    Abdeckung/Cursor, Sitzungsbündelung
backend/sync/provider_registry.py   ProviderId → Deskriptor, Job-Owner, Gate, Zeitplan
                         │
                         ▼
backend/db/…                        Repositories der kanonischen Tabellen
backend/runtime/ports.py            typisierte Lese-Ports
                         │
                         ▼
Domäne                              activities/ (Sitzungen, Feldpräzedenz),
                                    performance/ (SourcePolicy, Kennzahlen),
                                    planning/, nutrition/, athlete/, coach/
http_api/ + public/                 Lesemodelle mit kanonischen Namen und Provider-Schlüsseln
```

Neues Leaf-Paket **`backend/canonical/`**: nur Standardbibliothek, keine I/O,
keine Imports aus `backend`. Es enthält Vokabular und Datensatztypen und wird in
`tests/test_backend_layer_contracts.py` als eigene Schicht registriert, die alle
Schichten importieren dürfen, auch `providers` und `db`. Ohne Registrierung
stufte der Layer-Test es als „shared“ ein, und Provider-Adapter dürften es nicht
importieren. Ein eigenes Paket ist gerechtfertigt, weil Provider, Persistenz,
Domäne und HTTP den Vertrag gemeinsam nutzen und er keinem bestehenden
Domänenpaket gehört.

### 3.2 Kanonisches Vokabular

| Begriff | Werte (Startumfang) | Ersetzt |
| --- | --- | --- |
| `ProviderId` | `intervals`, `garmin`; später `wahoo` | freie Strings, Anzeige-Labels als Schlüssel |
| `SourceKind` | `provider`, `manual`, `derived`, `ai_estimate`, `fixture` | gemischte Labels für abgeleitete und geschätzte Werte |
| `RecordingOrigin` | `garmin_device`, `wahoo_device`, `zwift`, `manual_upload`, `unknown` … | `intervals_activity_device_source` und die `"wahoo"`-Namenskollision |
| `Sport` + `Environment` | `cycling`, `running`, `swimming`, `strength`, `walking`, `hiking`, `rowing`, `skiing`, `other`; Umgebung `outdoor`, `indoor`, `virtual` | die verteilten Klassifizierer, `VirtualRide` u. Ä. |
| `MetricKind` | jeweils mit fester Einheit: `sleep_duration` (s), `sleep_score`, `hrv` (ms, Methode RMSSD/SDNN), `resting_hr` (bpm), `readiness_score`, `body_battery`, `stress`, `steps`, `energy_expenditure` (kcal), `weight` (kg), `body_fat` (%), `vo2max`, `ftp` (W, je Sport), `threshold_hr`, `max_hr`, `threshold_pace` (s/km), `w_prime` (J), `fitness_ctl`, `fatigue_atl`, `form_tsb`, `race_prediction` (s, Distanz im Detail) | Aliasketten wie `ctl`/`ctLoad` oder `sleepScore`-Varianten in rund zehn Modulen |
| `LoadModel` | `intervals_load`, `garmin_training_load`, `local_estimate` | stilles Vermischen nicht vergleichbarer Belastungsmodelle |

Einheiten: Sekunden, Meter, m/s, Watt, bpm, kg, Prozent (0–100), kcal,
Millisekunden. Pace und Anzeigeformate entstehen erst im Lesemodell. Zeit:
`start_utc` plus Athleten-Zeitzone und athleten-lokaler `local_date` über
`backend/athlete/local_date.py`; naive Garmin-Ortszeiten löst der Mapper auf.
Deutsche Anzeigenamen stehen in genau einer Tabelle und erreichen das Frontend
über den Bootstrap.

### 3.3 Kanonische Datensätze

- **`Provenance`**: `provider`, `source_kind`, `provider_record_id`, `origin`,
  `observed_at`, `fetched_at`, `mapper_version`.
- **`ActivityRecord`**: eine Aufzeichnung eines Providers – Identität,
  Sport/Umgebung, Zeiten, Dauer (bewegt/gesamt), Distanz, Höhenmeter, HF (Ø/max),
  Leistung (Ø/normalisiert), Kadenz, Energie, `training_load` mit `load_model`,
  `intensity_pct`, RPE/Gefühl, Zonenzeiten mit Bezug auf die damals gültigen
  Schwellen, externe Verknüpfungsschlüssel (z. B. Upload- oder FIT-ID), Referenz
  auf ein gepaartes Planereignis des Providers sowie begrenzter Titel/Text als
  untrusted.
- **`ActivitySession`**: eine tatsächlich absolvierte Einheit, die eine oder
  mehrere Aufzeichnungen bündelt (Intervals-Kopie vom Wahoo, Intervals-Kopie von
  der Uhr, Garmin, später Wahoo direkt). Verknüpfungsart `exact`
  (gemeinsamer externer Schlüssel), `heuristic` (heutige Regeln) oder `confirmed`
  (Athlet); Primärquelle feldweise nach Präzedenz.
- **Identitätsregeln:** Eine Sitzung hat eine opake, lokale und stabile
  `activity_id` (z. B. `act_…`). `(provider, provider_activity_id)` identifiziert
  eine Aufzeichnung; ein wiederholter Sync erzeugt weder neue Aufzeichnungen noch
  neue Sitzungen. Alte Provider-IDs bleiben dauerhaft als Alias auflösbar, weil
  sie in Cursorn, Aufträgen und im Coach-Gesprächsverlauf stehen. Beim
  Zusammenführen zweier Sitzungen bleibt die ältere ID gültig, die andere wird
  zum Alias; beim Trennen behält die Primäraufzeichnung die ID. Zustände:
  Aufzeichnung `active`, `deleted` oder `invalid`; Sitzung `active`, `hidden`,
  `duplicate` oder `deleted`. Lokale Historie (Feedback, Analysen) wird nicht
  physisch gelöscht, wenn eine Aufzeichnung remote verschwindet.
- **Wertregeln für alle Datensätze:** Fehlende Werte sind `NULL`, nie `0`. Ein
  ungültiger Datensatz wird übersprungen und gezählt, blockiert aber nicht den
  ganzen Sync. Providerberechnete Werte (`icu_training_load`, eFTP, Garmin-Last)
  werden nicht neu berechnet; sie behalten `load_model` bzw. ihr Quellfeld und
  werden nicht als providerneutraler Wert ausgegeben.
- **`Observation`**: ein Tages- oder Punktwert mit `metric`, `value`,
  kanonischer Einheit, `local_date`, `observed_at`, optional `sport`, `method`
  und `aggregation`, strukturierten Details (z. B. Zonengrenzen,
  Prognosedistanz) und `Provenance`. Das schmale Langformat erlaubt neue Metriken
  und Provider ohne Schemaänderung. Schwellen und Zonen sind datierte
  Observations und erfüllen so die Regel, historische statt aktuelle Schwellen
  anzuwenden.
- **`ActivityDetail`**: Runden und Streams einer Aufzeichnung als Kanäle mit
  Einheit (heute nur Intervals, kv `activity_detail:*`).
- **`GearRecord`**, **`ProviderPlannedEvent`**, **`ProviderCompetition`**:
  Ausrüstung mit normalisiertem Status, eingehende Planereignisse und
  Wettkämpfe (`RACE_A/B/C` → Priorität A/B/C). Die Autorität bleibt bei den
  bestehenden lokalen Entitäten.
- **`MetricValue`** (Lesemodell): die verallgemeinerte Garmin-Hülle
  `{value, unit, source, freshness, fetched_at, observed_at, status}` für HTTP und
  Coach.

### 3.4 Persistenz (Schema v6, additiv)

Skizze; die endgültige DDL entsteht im Persistenz-PR.

| Tabelle | Zweck | Schlüssel |
| --- | --- | --- |
| `provider_records` | Unveränderte, untrusted Wire-Datensätze für Provenienz und Neuprojektion; `payload_hash`, `fetched_at`, `mapped_version` | `(provider, kind, provider_record_id)` |
| `activity_records` | Kanonische Aufzeichnungen; typisierte Spalten für Abfragen (Sport, `local_date`, Dauer, Distanz, Last …), validiertes kanonisches JSON (z. B. Zonenzeiten), Aufzeichnungszustand | eindeutig `(provider, provider_activity_id)`; Verweis auf `activity_sessions.activity_id` |
| `activity_sessions` | Bündelung, Primäraufzeichnung, Verknüpfungsart, Athletenbestätigung, Sichtbarkeit; zusammengeführte Sitzungen bleiben mit `merged_into` erhalten | opake, stabile `activity_id` |
| `observations` | Tages- und Punktwerte im Langformat | eindeutig je `(provider, metric, sport, method, observed_at bzw. local_date)` |

Bestehende Tabellen und kv-Einträge (`snapshots`, `garmin_snapshot`,
`activity_detail:*`, `equipment_assignment:*`, Ausrüstung) bleiben in v6
unverändert und werden weiter geschrieben (Dual-Write). Referenzen werden nicht
umgeschlüsselt, sondern über einen Resolver aufgelöst: lokale `activity_id` →
Primäraufzeichnung bzw. alte Provider-ID → `(provider, provider_activity_id)` →
Sitzung. Für `activity_feedback` ist keine Schemaänderung nötig, weil die
bestehenden IDs Intervals-IDs aus der Aktivitätsliste sind; der Backfill prüft
das und zählt nicht auflösbare Feedbackzeilen, die erhalten bleiben. Die
Providerspalte kam vorgezogen mit Schema v7 (#1130, P7-G). Die Cursor in `provider_sync_cursors`
– heute liest nur der Scheduler den `historical`-Cursor – werden zur
tatsächlichen Abdeckung je `(provider, Datenbereich)`.

**Atomarität:** Ingest schreibt Rohdatensätze, kanonische Datensätze und den
Legacy-Snapshot in derselben Transaktion; Cursor und Abdeckung folgen erst
danach. Schlägt der kanonische Schreibvorgang fehl, wird auch der Snapshot nicht
gespeichert und der Cursor nicht weitergesetzt. Provider-Abrufe laufen außerhalb
der Datenbanktransaktion.

**Löschregel:** Nur ein vollständig abgerufenes Fenster markiert darin fehlende
Aufzeichnungen als `deleted` – entsprechend dem heutigen Ersetzen bei
vollständigen Syncs. Inkrementelle oder unvollständige Abrufe löschen nie.
Bestätigte Remote-Löschungen über `activities/duplicate_service.py` markieren die
Aufzeichnung sofort; die Sitzung bleibt mit ihrer lokalen Historie erhalten.

**Neuprojektion und Backfill:** Ein idempotenter Wartungsjob projiziert alle
Rohdatensätze, deren `mapped_version` kleiner als die aktuelle Mapper-Version
ist. Die Schema-Migration legt nur Tabellen an und bleibt dadurch kurz,
transaktional und deterministisch. Die Erstbefüllung aus allen gespeicherten
Snapshots (älteste zuerst; `raw_provider_data`, ersatzweise `recent_activities`)
und aus `garmin_snapshot` übernimmt derselbe Job:

- Er arbeitet in kleinen Batches von 100–250 Datensätzen je Transaktion und ist
  nach einem Abbruch ohne Dubletten wiederaufnehmbar.
- Er erfasst Zähler ohne Inhalte: erkannte und gespeicherte Aufzeichnungen je
  Provider, erzeugte Sitzungen, erkannte Dubletten, übersprungene ungültige und
  bereits vorhandene Datensätze sowie nicht auflösbare Referenzen.

Bis zum Abschluss lesen die Verbraucher über die Legacy-Implementierung.

**Rohdaten** enthalten nie Tokens, Authorization-Header, Login-Antworten oder
signierte Download-URLs. Ein Test prüft das für jeden Mapper.

### 3.5 Quellenpräzedenz

Eine deklarative Tabelle je Kennzahl bzw. Aktivitätsfeld: geordnete
Providerliste, Höchstalter, Überschreibregel. Kennzahlen in
`backend/performance/source_policy.py`, Aktivitätsfelder bei der
Sitzungsbündelung in `backend/activities/`. Die Startwerte entsprechen dem
heutigen Verhalten (laut Analyse; Phase 0 schreibt es mit Tests fest):

| Bereich | Heutige Präzedenz |
| --- | --- |
| Aktivitäten, Details, Zonen | Intervals kanonisch; Garmin zählt nur ohne Treffer; innerhalb Intervals bleibt die Wahoo-Kopie |
| Schlaf, Schlafscore, Ruhepuls, HRV | Garmin vor Intervals-Wellness |
| Readiness | Intervals vor Garmin |
| Body Battery, Schritte, Energieverbrauch | nur Garmin; aktueller Morgenwert vor Historie |
| Gewicht | Garmin → Intervals-Wellness → Intervals-Athlet → manuell; für W/kg jüngster Wert ≤ 7 Tage, bei Gleichstand Garmin |
| FTP, Schwellen, VO2max, Prognosen, Max-HF | Garmin vor Intervals |
| Diagramme | Last aus Garmin; Trainingszeit und eFTP aus Intervals |

Ein neuer Provider erhält seinen Platz ausschließlich in dieser Tabelle.
Verschiedene `LoadModel`s werden nie stillschweigend in einer Reihe gemischt.

### 3.6 Provider-Register

`ProviderDescriptor` (statisch, in `backend/providers/`): `id`, Anzeige-Label,
Fähigkeiten (`activities`, `activity_details`, `daily_health`, `body`,
`thresholds`, `gear`, `planned_events`, `competitions`, `workout_export`),
Freshness-Bereiche mit Schwellen, Konfigurationsprüfung, Standard- und
Maximalfenster, Resync-Schlüssel und Zeitplanpolitik.

`backend/sync/provider_registry.py` verbindet Deskriptor, Job-Owner
(`ProviderJobOwner`-Protokoll nach Vorbild von `SyncJobRunner`), Gate und
Ingest-Pfad. Es ersetzt die festen Mengen und Verzweigungen in `sync/jobs.py`,
`daily.py`, `queue.py`, `gates.py`, `executor.py`, `full_resync.py`,
`scheduler.py`, `freshness.py`, `state.py`, `status.py` und `commands.py` sowie
`SYNC_PERIOD_DEFAULTS` in `server.py`. HTTP-Status, Frontend-Labels
(`PROVIDER_LABELS` in `public/sync-status.js`), Coach-Ziel-Enums
(`coach/authorization.py`, `coach/tool_schemas.py`), Diagnose und
Datenschutz-Export lesen aus dem Register. Bestehende HTTP-Routen bleiben
stabil; nur die Verteilung dahinter wird registergesteuert. Die Verdrahtung in
`server.py` bleibt geradlinige Komposition (eine Registrierung je Provider); der
Aufbau des Registers liegt in einem Assembly-Modul.

### 3.7 Outbound

- **`WorkoutExportPort`** je Ziel: Fähigkeiten (Planereignisse, Bibliothek,
  Wettkämpfe) sowie `serialize`, `upsert`, `delete`, `list_window` und
  `verify_readback`. Die Intervals-Implementierung entsteht durch Verschieben
  des bestehenden Codes; die REST-Aufrufe aus `sync/planned_calendar.py`
  wandern in `providers/intervals_client.py`.
- **Workout-Modell:** Der gespeicherte Workout-Text bleibt das dokumentierte
  interne Format (`docs/workout-export-format.md`), sodass bestehende Pläne nicht
  migriert werden müssen. `structured_steps` ist das kanonische
  In-Memory-Modell; jedes Ziel serialisiert daraus (Intervals: Text unverändert,
  Wahoo: Plan-JSON). Das Planungsvokabular wechselt auf `Sport`; nur der
  Intervals-Adapter bildet Intervals-Typen ab. Bereits gespeicherte Sportwerte in
  Ausrüstung, Bibliothek und Planeinheiten bleiben zunächst im Intervals-Vokabular
  und werden an der Lesegrenze übersetzt. Eine Umschreibung dieser Daten erfolgt
  erst im Rückbau mit eigener Migration. Zurückkopierte
  `icu_*`/`workout_doc`-Felder gehören zur Remote-Verknüpfung statt zum lokalen
  Datensatz.
- **`remote_links`** (`entity_kind`, `local_id`, `provider`, `remote_id`,
  `remote_external_id`, `baseline_hash`, `sync_state`, `last_synced_at`) ersetzt
  die Einzel-Slots; Tombstones erhalten eine Providerspalte. Umsetzen erst, wenn
  ein zweites Outbound-Ziel beauftragt ist (eigene Schemaversion).
- Die explizite Freigabe bleibt: keine impliziten Remote-Schreibvorgänge.
  Coach-Werkzeuge für Remote-Writes erhalten dann ein `target` aus dem Register;
  bis dahin bleiben die bestehenden Namen wie `start_intervals_plan_sync`.

## 4. Umsetzungsphasen

Jede Phase besteht aus mehreren kleinen PRs mit Conventional-Commit-Titeln.

### Phase 0 – Absicherung (ohne Verhaltensänderung außer 0.1)

1. **HRV-Fix** aus Abschnitt 1.3.
2. **Bereinigte Wire-Fixtures** je Provider unter
   `tests/fixtures/providers/<provider>/` mit synthetischen Werten, abgeleitet aus
   vorhandenen Testdaten und dem e2e-Standard-Fixture – keine echten
   Athletendaten.
3. **Charakterisierungstests** für Präzedenz und abgeleitete Werte:
   `current_metrics`, `recovery_context`, `planning_recovery`,
   `personal_recovery`, `body_history`, `load`/`load_context`, `chart_history`,
   `training_focus`, `calendar_projection`, `matching`, `duplicates` und die
   Coach-Kontextprojektion, außerdem Aktivitätsliste mit Paginierung
   (`activities/read_service.py`) und Analyse-Fingerprints
   (`performance/report_service.py`). Sie sind die Paritätsreferenz aller
   Folgephasen.
4. **Migrationsgerüst:** eingefrorene SHA-256-Digests der normalisierten
   Schemasignatur je veröffentlichter *Form* statt Rückrechnung aus dem aktuellen
   Schema. Formen: S1 (Release 1.12.19), S2 (v2), S3 (v3 und v4 sind
   tabellengleich), aktuell (v5, live aus dem Code berechnet). Exakte Erkennung
   per Lookup `user_version → zulässige Formen` (0 → S1/S2/S3/aktuell, 1 → S1,
   2 → S2, 3 und 4 → S3, 5 → aktuell); alles andere wird vor jedem Schreibzugriff
   abgewiesen. Schritte je Form: S1 → S2 (Nutrition-Produkte-DDL), S2 → S3
   (`no_training` mit Backfill und Refresh-Marker), S3 → aktuell
   (`logged_time_known`); `_remove_gemini_state` bleibt unbedingter Nachschritt.
   Ein Savepoint, frühe No-op-Rückkehr und Endvalidierung gegen die
   Live-Signatur bleiben; verhaltensgleich, bestehende Migrationstests
   unverändert grün. Die Digests werden nie zur Laufzeit aus `tests/fixtures`
   geladen. Das v4-Fixture `schema_v4.sql.txt` existiert bereits; das
   v5-Fixture wird nach dem nächsten Release eingefroren.
5. **Garmin-Lock-Identität:** Heute gibt es kein Race auf `garmin_snapshot` –
   Garmin-Sync und Morgen-Body-Battery teilen `GARMIN_SYNC_LOCK`
   (`server.py:558-563`, `sync/garmin_service.py:32-37`,
   `http_api/garmin_assembly.py:174-178`). Die Kopplung ist aber nur verdrahtet;
   ein Identitätstest sichert sie bis zum einzigen Schreibpfad in Phase 3.

Abnahme: volle Suite, Qualitäts-Ratchet ohne neue Befunde. Größe: mittel.

### Phase 1 – Kanonischer Vertrag und Mapper

1. `backend/canonical/` mit Vokabular, Datensätzen und Validierung von Einheiten
   und Wertebereichen; Registrierung im Layer-Test.
2. Mapper je Provider und Datenbereich in `backend/providers/`
   (`intervals_activity_mapping.py`, `intervals_wellness_mapping.py`,
   `garmin_activity_mapping.py`, `garmin_health_mapping.py`): reine Funktionen
   mit `MAPPER_VERSION`, die ein `MappingResult` aus Datensätzen und
   wertfreien `MappingIssue`s liefern. Sie bündeln die verstreuten
   Garmin-Schlüsselhelfer und Intervals-Aliasketten und ordnen Sportarten zu.
3. Ein zentraler Sport-Klassifizierer mit Labeltabelle; bestehende
   Klassifizierer delegieren zunächst dorthin.
4. **Architektur-Guard mit Ratchet-Baseline** (analog `quality_baseline.json`):
   Provider-Feldnamen (`icu_*`, bekannte Garmin-Wire-Schlüssel) außerhalb von
   `backend/providers/` und Providernamen-Literale außerhalb von Register,
   Mappern, Verdrahtung und Migrationen. Neue Fundstellen schlagen fehl; die
   Baseline schrumpft mit jeder Phase.

Abnahme: Mapper-Tests gegen die Fixtures (fehlende und umbenannte Felder,
Einheiten, Zeitzonen und Sommerzeitwechsel, Dubletten), Layer-Tests,
Guard-Baseline. Größe: mittel.

### Phase 2 – Kanonische Leseschicht über Bestandsdaten

1. Typisierte Ports in `backend/runtime/ports.py`: `ActivityReader`
   (Aufzeichnungen, Sitzungen, Details), `ObservationReader` (Zeitreihen,
   aktuelle Werte) und `ProviderCoverageReader`.
2. Legacy-Implementierung in `backend/sync/`: projiziert `snapshots` und
   `garmin_snapshot` beim Lesen über die Mapper, zwischengespeichert je
   Snapshot-Stand.
3. `SourcePolicy` und Sitzungsbündelung; sie ersetzen die Laufzeit-Dubletten und
   die ungenutzten `activity_matches`. Sitzungen bleiben in dieser Phase intern:
   Eine beim Lesen berechnete Sitzung hat keine stabile ID. Nach außen bleibt
   die Provider-ID die Referenz, bis Phase 3 stabile IDs speichert.

Abnahme: Paritätstests – die Charakterisierungsergebnisse sind aus kanonischen
Daten identisch zu heute. Größe: mittel.

### Phase 3 – Kanonische Persistenz und Aktivitätsidentität (Schema v6)

Kommt vor der Verbraucherumstellung, weil Feedback, Ausrüstung, Analysen,
Paginierung und Coach-Werkzeuge stabile IDs brauchen, sobald sie kanonische
Aktivitäten verwenden.

1. Migration v6 (additiv, Schritt „aktuell (v5) → v6“ im Gerüst aus 0.4) mit
   allen Nachweisen aus Abschnitt 6.
2. Ingest-Schreibpfad nach Abschnitt 3.4: Intervals- und Garmin-Jobs schreiben
   Rohdatensätze, kanonische Datensätze und den Legacy-Snapshot in derselben
   Transaktion (Dual-Write), Cursor zuletzt. `garmin_snapshot` erhält genau einen
   Schreibpfad; heute schreiben Sync und Morgen-Body-Battery getrennt, aber
   unter demselben `GARMIN_SYNC_LOCK`.
3. Neuprojektions- und Backfill-Job: idempotent, an die Mapper-Version gebunden,
   in Batches wiederaufnehmbar, Zähler in der Diagnose ohne Athleteninhalte.
4. Referenz-Resolver für lokale und alte Provider-IDs. Er wird verwendet von
   Detailansicht und Detailabruf (`performance/activity_read_service.py`,
   `sync/activity_details.py`), Feedback, Detailcache,
   Ausrüstungszuordnung, eingereihten `activity_details`-Aufträgen,
   Duplikatlöschung und Coach-Werkzeugen. Die API liefert weiter `id` (Provider-ID)
   und zusätzlich `activity_id`. Alte Paginierungscursor funktionieren weiter; ein
   neues Cursorformat erhält eine Versionskennung.
5. Tabellenbasierte Port-Implementierung; Umschalten nach erfolgreichem Backfill
   und Paritätsprüfung Legacy gegen Tabelle. Die Parität umfasst:
   - Listenlänge (heute auf 500 gekürzt), Sortierung, Filter und Paginierung;
   - unveränderte `summary_sha256`-Fingerprints, sonst verschwinden
     gespeicherte Analysen aus Berichten und Saisonvorbereitung;
   - Lesbarkeit der zuletzt gespeicherten Daten ohne Provider-Sync.

Abnahme: Migrations-, Restore-, Restart- und SQLCipher-Nachweise,
Backfill-Tests mit Fixture-Daten einschließlich Abbruch und Wiederaufnahme,
Atomaritätstest (Persistenzfehler setzt weder Snapshot noch Cursor),
Resolver-Tests mit alten IDs und Cursorn, `docker build`. Größe: groß.

Status: Schritte 1 (#1100), 2 (#1103), 3 (#1105) und 4 (#1106) umgesetzt;
Ergebnis in Abschnitt 5.10. Schritt 5 (#1107) umgesetzt; Ergebnis in Abschnitt 5.11.

### Phase 4 – Provider-Register und Orchestrierung

Umsetzung nach Abschnitt 3.6. Kann nach Phase 1 parallel zu den Phasen 2, 3 und
5 laufen.

Abnahme: Ein nur in Tests registrierter, gemockter Provider durchläuft
Zeitplanung, Queue, Ausführung, Freshness, Status, HTTP-Status und Coach-Refresh
ohne Änderungen außerhalb seiner Registrierung. Größe: mittel bis groß.

Status: umgesetzt (#1076 bis #1090); Ergebnis und offene Punkte in Abschnitt 5.6.

### Phase 5 – Verbraucher umstellen (je Domäne ein PR)

1. `performance/`: Kennzahlen, Last/Form, Erholung, Body, Diagramme,
   Trainingsfokus, eFTP, Berichte.
2. `activities/`, `planning/` (Tages- und Kompaktkontext), `nutrition/`
   (Energieverbrauch) und `athlete/equipment.py` über `GearRecord`; die lokale
   Autorität bleibt.
3. HTTP-Lesemodelle und PWA: kanonische Feldnamen (`training_load`, `moving_s`
   …; `id` bleibt bis zum Rückbau die Provider-ID, `activity_id` ist die lokale
   ID) und `provider`-Schlüssel statt Labelvergleichen in `public/plan-views.js`,
   `analysis.js`, `performance-view.js`, `activity-details.js` und `views.js`;
   Labels aus dem Bootstrap; Asset-Versionen in `public/index.html` und
   Service-Worker-Cache aktualisieren.
4. Coach: Kontextabschnitte nach Fachbereich (Aktivitäten, Erholung, Körper,
   Leistung, Planung) statt nach Provider, jeder Wert mit Quelle und Messdatum,
   Budget je Abschnitt, Quellenpolitik-Text aus dem Register und angepasstes
   Abschnitts-Enum von `read_coach_context`. Prüfung nach
   `.agents/skills/ai-coach-coach-contracts` und den Fällen in
   `docs/coach-dialogue-evaluation.md`.

Abnahme: Paritätstests, sinkende Guard-Baseline, Playwright für die betroffenen
Ansichten in allen fünf Projekten, Coach-Kontexttests für Quelle und Freshness.
Größe: groß (mehrere PRs).

### Phase 6 – Outbound-Port und Workout-Modell

1. `WorkoutExportPort` mit Intervals-Implementierung (Verschiebung) und
   REST-Aufrufen im Client.
2. Planungsvokabular auf `Sport`; Serialisierer aus `structured_steps`.
3. `remote_links` (eigene Schemaversion), nur mit beauftragtem zweitem Ziel.

Größe: mittel (6.1–6.2), groß (6.3).

Status: 6.1 (#1101) und 6.2 (#1102) umgesetzt; Ergebnis in Abschnitt 5.9.
6.3 bleibt bis zu einem beauftragten zweiten Ausgabeziel offen.

### Phase 7 – Rückbau

Legacy-Leser und Dual-Write entfernen, `snapshots` auf Sync-Metadaten mit
begrenzter Aufbewahrung reduzieren, `garmin_snapshot` auf Zustandsdaten
beschränken, `activity_feedback` um eine Providerspalte ergänzen, gespeicherte
Sportwerte in Ausrüstung, Bibliothek und Planeinheiten auf `Sport` umschreiben,
Guard-Baseline leeren. Dafür eine eigene, datenbewahrende Migration: Gelöscht
wird nur, was nach verifiziertem Backfill vollständig in `provider_records`
liegt. Alte Provider-IDs bleiben auch danach über den Resolver auflösbar. Snapshots
bleiben mehrere Releases lang als Rückfallquelle erhalten, bevor sie reduziert
werden. Größe: mittel.

### Phase 8 – Wahoo als Abnahmefall

Siehe Abschnitt 7.

## 5. Abhängigkeiten und Reihenfolge

| Schritt | Benötigt | Beispiel-PR-Titel |
| --- | --- | --- |
| 0.1 HRV-Fix | – | `fix(performance): derive Intervals HRV method from wellness fields` |
| 0.2–0.3, 0.5 Fixtures, Charakterisierung, Lock-Test | – | `test(performance): characterize recovery source precedence` |
| 0.4 Migrationsgerüst | – | `refactor(db): recognize released schemas by frozen signatures` |
| 1 Vertrag, Mapper, Guard | 0.2–0.3 | `feat(canonical): add provider-independent records and mappers` |
| 2 Leseschicht | 1 | `refactor(sync): read provider snapshots through canonical ports` |
| 3 Persistenz v6, Identität | 0.4, 2 | `feat(db): persist canonical provider records in schema v6` |
| 4 Register | 1 | `refactor(sync): drive provider orchestration from a registry` |
| 5 Verbraucher | 3 | `refactor(performance): consume canonical observations` |
| 6 Outbound | 4 | `refactor(planning): export workouts through a provider port` |
| 7 Rückbau | 3, 5 | `refactor(sync): remove legacy provider snapshot reads` |
| 8 Wahoo | 3, 4, 5; bei Outbound auch 6 | `feat(providers): add Wahoo provider` |

Kritischer Pfad bis „neuer Provider ohne Domänenänderung“: 0 → 1 → 2 → 3 → 5,
mit 4 parallel.

### 5.1 Umsetzungswellen

Parallel umsetzbar sind nur unabhängig mergebare PRs gegen `develop`. Die
Umsetzung läuft deshalb in Wellen; jede Welle startet erst, wenn die vorige
gemergt ist.

| Welle | Inhalt | PRs |
| --- | --- | --- |
| 1 ✅ | Phase 0 vollständig; aus Phase 1 das Leaf-Paket `backend/canonical/` (Vokabular, `Provenance`, `ActivityRecord`, `Observation`, `MetricValue`, Validierung, Layer-Registrierung) und der Kopplungs-Guard mit zählerbasierter Baseline | 12 (#1043–#1054): HRV-Fix; Wire-Fixtures mit Lock-Identitätstest; sieben Charakterisierungs-PRs (aktuelle Metriken, Recovery, Körper-/Chart-Historie, Last/Fokus, Aktivitätsidentität, Coach-Kontext, Aktivitätslesen); Migrationsgerüst; kanonisches Paket; Guard |
| 2 ✅ | Phase 1.2/1.3 und Beginn Phase 4: Intervals- und Garmin-Mapper gegen die Wire-Fixtures, zentraler Sport-Klassifizierer, Provider-Deskriptoren im Register | 7 (#1057, #1058, #1060–#1064): kanonische Grundlagen (`sports.py`, `local_time.py`, `mapping.py`, `Observation.sport`); Register (`providers/descriptors.py`, `sync/provider_registry.py`, freshness/state lesen daraus); je ein Mapper für Intervals-Aktivitäten, Intervals-Wellness/-Schwellen, Garmin-Aktivitäten, Garmin-Gesundheit; `activity_kind` delegiert an den Klassifizierer (Paritätstabelle mit 217 Eingaben) |
| 3 ✅ | Phase 2: kanonische Leseschicht über Bestandsdaten, verhaltensgleich gegen die Charakterisierungstests, noch ohne Verbraucher | 6 (#1066–#1071): Sitzungsbündelung (`activities/canonical_sessions.py`); Leser-Ports und `ProviderCoverage` (`runtime/ports.py`, `canonical/coverage.py`); Garmin-Gewicht/-Körperfett wie Legacy (`MAPPER_VERSION` 2) mit Paritätstests; Intervals-Paritätstests; `SourcePolicy` (`performance/source_policy.py`); Snapshot-Projektion (`providers/snapshot_projection.py`, `sync/canonical_projection.py`) |
| 4 | Paritätslücken schließen, erste Verbraucher auf Ports und `SourcePolicy`, danach Phase 3 (Schema v6, Ingest-Dual-Write, Backfill-Job, Aktivitätsidentität) | siehe 5.5; Schema-PRs sequenziell |
| 5+ | Phasen 5–8 | je Domäne ein PR |

Konfliktregeln für Welle 1: Nur HRV-Fix, Migrationsgerüst und kanonisches Paket
ändern bestehende Python-Dateien. HRV-Fix und Migrationsgerüst fügen keine
`icu_*`-Bezeichner, Garmin-Wire-Schlüssel oder `"intervals"`/`"garmin"`-Literale
hinzu oder entfernen sie, damit die Guard-Baseline nach allen Merges gültig
bleibt. Der Guard erlaubt `backend/providers/` und `backend/canonical/` vorab.

### 5.2 Ergebnis Welle 2: bekannte Abweichungen

Die Mapper haben noch keine Verbraucher; das App-Verhalten ist unverändert.
Die folgenden Unterschiede zwischen Mappern und heutigen Lesern sind in den
Modul-Docstrings und PRs dokumentiert und müssen vor dem Umschalten in Welle 3
entschieden oder durch Paritätstests abgesichert werden:

- **Garmin-Gewicht und -Körperfett:** Der Mapper liest nur flache Datensätze
  mit `calendarDate` und ausdrücklicher Einheit. `performance/garmin_weight.py`
  durchsucht verschachtelte Antworten, liest `weightKg`, `summaryDate` und
  Epoch-Zeitstempel, rät Gramm ab Werten über 300 und kennt Körperfett als
  Anteil. Echte Garmin-Antworten können deshalb heute im Mapper nur Issues
  erzeugen. Vor dem Umschalten: Mapper um diese Formen erweitern oder die
  Fixtures um reale Antwortformen ergänzen (Fixture-Mengentest anpassen).
- **Garmin `running_threshold`:** ohne Datum, daher Abruftag in der Zone des
  Athleten; Schwellenleistung wird als `unsupported` gemeldet, weil ihr Sport
  nicht eindeutig ist.
- **Garmin-Aktivitäten:** `recorded_by` ist immer `GARMIN` (der Payload hat
  kein Gerätefeld); Dauer `duration` vor `movingTime` wie im Legacy-Code, die
  Semantik beider Felder ist nicht gegen die Garmin-API geprüft.
- **Intervals-Aktivitäten:** Startzeit `start_date` (aware) vor
  `start_date_local`; andere Leser bevorzugen `start_date_local`.
  `moving_time = 0` gilt als ungültig. Ein `trainer`-Flag wird nicht gelesen.
- **Intervals-Wellness/-Schwellen:** Komma-Dezimalzahlen werden abgelehnt
  (Leser akzeptieren sie); ein verworfener `sportSettings`-FTP erlaubt den
  `icu_ftp`-Fallback (`current_metrics` nicht); ungültiger Erst-Alias fällt
  nicht auf den zweiten zurück.
- **Sport-Klassifizierung:** `activity_kind` und `activity_sport` widersprechen
  sich bei Mischfeldern (`{"type": "Run", "sport": "Ride"}` ist Rad bzw.
  Laufen). Legacy-Lücken: Garmin `road_biking`, `mountain_biking`, `biking`
  → other, „Langlauf“ → running; Teilstring-Fehltreffer („stride“, „brunch“,
  „Growth“, „Narrow“, „personal trainer“). Die Paritätstabelle friert sie
  ein; eine Korrektur ist eine bewusste Verhaltensänderung mit eigenem PR.
- **Register:** `freshness.py` hält Konfigurationsprüfungen und Fallbacks noch
  selbst; `http_api/sync_commands.py` nennt 365/90 Tage hartkodiert;
  `resync_keys` und Capabilities haben noch keinen Verbraucher; `daily.py`
  ist unverändert.

### 5.3 Vorschlag Welle 3 (umgesetzt, siehe 5.4)

Ziel: Phase 2, kanonische Leseschicht über `snapshots` und `garmin_snapshot`,
verhaltensgleich gegen die Charakterisierungstests aus Welle 1.

1. **Paritätsgrundlage (zuerst, ein PR je Provider):** Mapper-Lücken aus 5.2
   schließen, die für die Parität nötig sind (Garmin-Gewicht/-Körperfett,
   Komma-Dezimalzahlen nach heutiger Leser-Semantik oder dokumentierte
   Abweichung), und Paritätstests Mapper gegen heutige Leser auf den Fixtures.
2. **Ports:** `ActivityReader`, `ObservationReader`, `ProviderCoverageReader`
   in `backend/runtime/ports.py` (nur Protokolle und Tests).
3. **Legacy-Projektion:** Implementierung in `backend/sync/`, die Snapshots
   beim Lesen über die Mapper projiziert und je Snapshot-Stand cacht; Issues
   werden gezählt (Diagnose ohne Athleteninhalte), nie geloggt.
4. **`SourcePolicy`:** Quellenpräzedenz nach 3.5 als eigene Einheit mit
   Tabellen-Tests, zunächst exakt die heutige Präzedenz (inklusive der in
   Welle 1 festgeschriebenen Fehlerfälle); Korrekturen danach einzeln.
5. **Sitzungsbündelung:** Dublettenerkennung Intervals/Garmin/Wahoo über
   kanonische Datensätze, verhaltensgleich zu `activities/duplicates.py`.

Die Persistenz v6 (Phase 3) bleibt Welle 4 und setzt Welle 3 voraus. Vor
Welle 4 ist das veröffentlichte Schema v5 als Fixture einzufrieren, sobald es
released ist.

### 5.4 Ergebnis Welle 3: Leseschicht und bekannte Abweichungen

Alle neuen Bausteine haben noch keine Produktionsverbraucher; `server.py`, HTTP,
Frontend und bestehende Leser sind unverändert. Neue Module sind zu 100 %
abgedeckt.

- **Ports (#1067):** `ActivityReader.activities(db, *, start, end)`,
  `ObservationReader.observations(db, kind, *, start, end, sport)` und
  `ProviderCoverageReader.coverage(db)`; Datumsgrenzen inklusiv auf dem lokalen
  Datum des Athleten. `ProviderCoverage` zählt Aktivitäten, Beobachtungen und
  Issues je Grund (`count_issues`), nie Feldnamen oder Werte.
- **Projektion (#1071):** `CanonicalSnapshotProjection` implementiert alle drei
  Ports über injizierte Callables (Intervals-Snapshot und -Version,
  Garmin-Payload, Zone, Uhr). Cache-Schlüssel: Intervals-Version, SHA-256 des
  Garmin-Payloads und Zone, unter `threading.Lock`. Projektionen ohne
  gespeicherte Sync-Zeit (Uhr-Fallback) werden nicht gecacht, damit sie nicht
  über Mitternacht veralten. Korrekt ist das nur, wenn der Schreiber den
  Snapshot vor dem Versionswechsel festschreibt (im Docstring festgehalten).
  `retrieved_at = None` in der Coverage bedeutet „keine gespeicherte Sync-Zeit“.
- **Garmin-Gesundheit (#1068):** Gewicht/Körperfett folgen
  `performance/garmin_weight.py` (Abschnitte `weight`/`weigh_ins`/`weighIns`,
  beschränkte Rekursion, Gramm-Heuristik ohne Einheit, Epoch-ms als UTC-Datum,
  `observed_at` aus dem Zeitstempel). Die Walker-Logik ist aus dem Legacy-Code
  dupliziert; eine gemeinsame Extraktion folgt.
- **Intervals-Parität (#1069):** 28 Paritätstests; ein `expectedFailure`: Dem
  Mapper fehlt der athletenweite `lthr`/`max_hr`-Fallback.
- **`SourcePolicy` (#1070):** `select_current`/`select_daily` bilden die
  heutige Präzedenz tabellengesteuert ab. Der Aufrufer übergibt
  `latest_wellness_day`, weil kanonische Datensätze ein fehlendes Feld nicht
  abbilden; nur Intervals-Werte dieses Tages zählen. Gleiche Garmin-Tage je
  Sicht wie heute: Gewicht nach Zeitstempel, dann letzte Eingabe; Recovery,
  Ruhepuls, FTP letzte Eingabe; Planungs-HRV erste Eingabe. Sportbezogene
  Auswahl ist datumsblind; `sportSettings` behalten den ersten Eintrag.
  Offene, gepinnte Mapper-Lücken: `cycling_ftp_history`, Garmin-Schlafscore 0,
  Athletengewicht, Max-HF aus Garmin-Herzfrequenzzonen, VO2max aus
  `sportSettings`. VO2max- und Max-HF-Hilfsfunktionen sind durch Tests, aber
  nicht zeilenweise gegen den Legacy-Code abgeglichen.
- **Sitzungsbündelung (#1066):** `bundle_sessions(records, *, zone)` vergleicht
  wie Legacy auf lokaler Wandzeit. Gepinnte Abweichungen: fehlende oder
  0-`moving_time` bei Intervals, 0-Dauer bei Garmin, Garmin-Start in einer
  DST-Lücke; `latest_wahoo_garmin_duplicate` betrachtet heute nur Paare mit
  der neuesten Aktivität. Intervals-Sport kommt aus der Typ-Tabelle (ohne
  Namen); Aufzeichnungen außerhalb der Zone können anders vergleichen. Die
  Kandidatensuche ist quadratisch und braucht vor einem Lesepfad eine
  Fenstersuche.

### 5.5 Vorschlag Welle 4

1. **Paritätslücken schließen (ein PR je Provider):** Intervals-Mapper um den
   athletenweiten `lthr`/`max_hr`-Fallback, `cycling_ftp_history`,
   Athletengewicht und VO2max aus `sportSettings`; Garmin-Mapper um Schlafscore
   0 und Max-HF aus Herzfrequenzzonen. Jeweils `MAPPER_VERSION` erhöhen und die
   gepinnten Abweichungstests in Paritätstests umwandeln.
2. **Härtung:** gemeinsamen Garmin-Gewichts-Walker aus
   `performance/garmin_weight.py` extrahieren (eine Implementierung für Leser
   und Mapper); Fenstersuche statt quadratischer Kandidatensuche in
   `canonical_sessions.py`.
3. **Verdrahtung ohne Verbraucherwechsel:** `CanonicalSnapshotProjection` im
   Composition Root mit den bestehenden Snapshot-Lesern verdrahten und die
   Coverage-Zählungen in die sichere Diagnose aufnehmen (nur Zähler, keine
   Athleteninhalte).
4. **Erste Verbraucher (je Domäne ein PR):** zuerst `load_context` und
   `current_metrics` über Ports und `SourcePolicy`, gesichert durch die
   Charakterisierungstests aus Welle 1; danach Recovery und Aktivitätslesen.
5. **Schema v6 (sequenziell, nach Einfrieren des veröffentlichten v5):**
   additive Tabellen, Ingest-Dual-Write, Backfill-Job und Aktivitätsidentität
   mit den Pflichtnachweisen aus Abschnitt 6.

### 5.6 Ergebnis Phase 4: Provider-Register und Orchestrierung

Die Orchestrierung ist für Intervals.icu, Garmin, Wetter und Kalender
registergesteuert und verhaltensgleich: Jobs, Zeitplanung, Ausführung,
Freshness, Status, Vollresync, HTTP-Befehle und Coach-Refresh lesen aus dem
Register; `server.py` bleibt reine Komposition. Der Bootstrap-JSON ist
unverändert. Ausgenommen ist das Frontend (siehe unten).

| Einheit | PR | Inhalt |
|---|---|---|
| U1 | #1076 | Deskriptor um Orchestrierungspolitik erweitert, Laufzeit-Typen (`provider_runtime.py`) |
| U3 | #1084 | Jobtypen, Refresh-Felder und Tagesmarker aus dem Register |
| U4 | #1083 | Dispatch über `ProviderJobOwner` |
| U5 | #1079 | Tages- und Startreihenfolge nach Deskriptor-Rang, Policies je Provider |
| U6 | #1082 | Freshness und Status aus Quellen je Provider und Bereich |
| U7 | #1086 | Vollresync über registrierte Handler |
| U8 | #1085 | Coach-Ziel-Enum, Refresh-Ziele und Warte-Flag aus dem Register |
| U9 | #1078 | HTTP-Pfade und Texte für Sync-Befehle über das Register |
| U9b | #1088 | Register durch die restlichen Sync-Gates (Executor, Persistenz) |
| U10 | #1087 | `provider_runtime_assembly.py`, Runtime-Registry in alle Assemblies |
| U11 | #1090 | `server.py`: eine lazy Runtime-Fabrik, `SYNC_PERIOD_DEFAULTS` abgeleitet |
| U12 | #1089 | Abnahmetest mit Mock-Provider `acme` |

- **Abnahme (#1089):** `tests/test_provider_runtime_acceptance.py` registriert
  `acme` nur im Test. 21 Tests laufen durch Zeitplanung (Start und täglich),
  Queue und Normalisierung, Executor, Freshness und Status, die HTTP-Route
  (202/400/409) und den Coach-Refresh (Enum, asynchron oder wartend). Ein
  Negativtest stellt sicher, dass `DEFAULT_PROVIDER_REGISTRY` unverändert
  bleibt. Die vollständige Suite lief mit 4575 Tests ohne Fehler.
- **Nachweise #1090:** vollständige Suite (4558 Tests, 18 nativ übersprungen),
  `docker build -t ai-coach:local .` und die vier Wiring-Tests im gebauten Image
  (darunter die zwei SQLCipher-Tests, die nativ unter Windows überspringen).
- **Guards:** Kopplungs-Baseline sank durch die entfernten Literale
  (jeweils per `--snapshot` festgehalten); die Registrierung bleibt literalfrei.

Bekannte Lücken (die ersten beiden sind im Abnahmetest als
`expectedFailure` gepinnt, also noch nicht behoben):

1. **`performance_refresh`-Single-Flight:** `SyncJobStore.enqueue` und
   `pending_performance_job_id` in `backend/sync/jobs.py` sind fest auf Intervals
   verdrahtet; ein zweiter Provider mit diesem Jobtyp wird nicht entdoppelt.
2. **Zeitraumgrenze in der Queue:** `_normalize_refresh_days` nutzt die feste
   Grenze 3660 und ignoriert `max_sync_days`; nur `set_sync_period` erzwingt sie.
   Über die Queue wird `days=61` für `acme` (Grenze 60) angenommen. Die Korrektur
   ändert das Verhalten aller Provider und gehört in einen eigenen PR.
3. **Startplaner und `blocked()`:** Der Startplaner fragt `blocked()` nicht ab,
   weil das Protokoll keinen Auslöser kennt; gleiches Verhalten wie zuvor.
4. **Duplizierte Laufprüfung:** Das Intervals-Laufprädikat steht zusätzlich in
   `intervals.py` (um Zeile 623); der Running-Probe in `freshness_sources.py`
   dupliziert es.
5. **Ablehnungstext:** Die Meldung „Intervals.icu“ bei nicht konfigurierten
   Providern wird providerübergreifend geteilt.
6. **Frontend:** `PROVIDER_LABELS` in `public/sync-status.js` bleibt bewusst
   außen vor und wird in einer späteren Welle aus dem Bootstrap gespeist.
7. **Persistenz in `server.py`:** `registry=` für `state_repository` und
   `daily_markers` ist nicht verdrahtet (rund zwölf Aufrufstellen); die Defaults
   sind identisch mit dem Register, es besteht also kein Verhaltensunterschied.
8. **`sync_commands.py`:** vier parallele Akzeptanzflächen; die Mengen werden je
   POST neu gebaut.
9. **Hinweise aus dem Review von #1090 (nicht eigenständig verifiziert):**
   `build_provider_runtime` prüft Bindings nicht gegen
   `DEFAULT_PROVIDER_DESCRIPTORS` (P2); `_runtime_executor` reicht das Register
   der Runtime nicht durch und teilt den Historical-Owner (P3); ein Kommentar zu
   `SYNC_PERIOD_DEFAULTS` in `descriptors.py` könnte veraltet sein (P3).

Vorschlag: ein Folge-PR schließt die Lücken 1 und 2 (Verhaltensänderung,
getrennt von der verhaltensgleichen Komposition) und prüft Punkt 9; Lücken 3 bis
5 und 7 bis 8 sind Aufräumarbeiten ohne Dringlichkeit.

**Stand nach #1091:** Lücken 1, 2 und 9 sind geschlossen. Die Queue erzwingt
`max_sync_days` je Provider (Zeitraumfehler 400), der
`performance_refresh`-Single-Flight gilt je Provider
(`pending_performance_job_id(provider)`), `build_provider_runtime` weist
Deskriptoren ohne Binding ab und `_runtime_executor` reicht das Register der
Runtime durch. Lücken 4, 5, 7 und 8 laufen in Welle 5; Lücke 3 bleibt
verhaltensgleich offen, Lücke 6 folgt mit Phase 5 (PWA).

### 5.7 Reihenfolge ab Welle 5

Entscheidung: Phase 3 (Schema v6) wird vor den ersten Verbrauchern (5.5 Punkt 4)
umgesetzt, weil die Verbraucher sonst zweimal umgestellt würden (erst auf die
Snapshot-Projektion, dann auf die Tabellen). Welle 5 bereitet Phase 3 parallel
vor:

| Einheit | Inhalt |
|---|---|
| W5-1 | v5 aus Release 1.12.31 als Fixture eingefroren, befülltes Upgrade und Same-Build-Restart |
| W5-2 | Intervals-Paritätslücken (`lthr`/`max_hr`-Fallback, `cycling_ftp_history`, Gewicht, VO2max) |
| W5-3 | Garmin-Paritätslücken (Schlafscore 0, Max-HF aus Zonen), gemeinsamer Gewichts-Walker |
| W5-4 | Fenstersuche in `canonical_sessions.py` mit Referenzparität |
| W5-5 | `CanonicalSnapshotProjection` verdrahtet, Coverage in der Diagnose, `registry=` in `server.py` |
| W5-6 | Aufräumlücken 4, 5 und 8 |

Danach sequenziell Phase 3 (Migration, Dual-Write, Backfill, Resolver,
tabellenbasierter Port), Phase 5 je Domäne, Phase 6.1/6.2, Phase 7 und Phase 8.

### 5.8 Ergebnis Welle 5 und Phase 3 Schritt 1

Welle 5 ist gemergt:

| Einheit | PR |
|---|---|
| W5-1 | #1095 |
| W5-2 | #1099 |
| W5-3 | #1093 |
| W5-4 | #1092 |
| W5-5 | #1094 |
| W5-6 | #1096 |

Von den Paritätslücken bleibt nur Lücke 3 (Garmin-Radfahr-FTP-Historie)
bewusst offen. Mit W5-2 liefert Intervals das Athletengewicht als undatierte
Beobachtung auf Athletenebene. `SourcePolicy` rankt sie ohne Datum und nimmt
sie von der Beschränkung auf die neueste Zeile aus.

Phase 3 Schritt 1 ist mit #1100 umgesetzt (Schema v6, additiv). Die DDL folgt
diesen Entscheidungen:

- **CHECKs:** nur für geschlossene Lebenszyklus-Enums aus
  `backend/canonical/vocabulary.py`:
  - `ProviderRecordState`: `active`, `deleted`;
  - `ActivityRecordState`: `active`, `deleted`, `invalid`;
  - `ActivitySessionState`: `active`, `hidden`, `duplicate`, `deleted`;
  - `ActivityLinkKind`: `single`, `exact`, `heuristic`, `confirmed`.

  Daneben prüft die Datenbank nur noch `json_valid` und Längen.

  Offene Vokabulare (Provider, Sport, Metrik, Einheit, Lastmodell, Quelle) und
  Wertebereiche validiert `backend/canonical` vor dem Schreiben. So wird ein
  ungültiger Datensatz übersprungen und gezählt, statt den Ingest abzubrechen.
- **`activity_sessions`:** Es gibt keine Eindeutigkeit auf der
  Primäraufzeichnung, weil die Primärquelle nach Präzedenz wechseln darf.
  `state = 'duplicate'` gilt genau dann, wenn `merged_into` gesetzt ist.
- **`activity_records`:** Schlüssel ist `(provider, provider_activity_id)`;
  `activity_id` ist ein optionaler Fremdschlüssel auf die Sitzung. Typisierte,
  nullbare Spalten sind:
  - Dauer, Bewegungszeit, Distanz, Höhenmeter;
  - Last, Intensität;
  - Herzfrequenz (Ø/Max), Leistung (Ø/NP), Kadenz, Energie.

  Weitere Werte stehen im JSON-Feld `details`.
- **`observations`:** Eindeutig ist der `natural_key`
  `provider|metric|sport|method|(observed_at oder observed_on)`.
- **`provider_records`:** `payload_hash` wird über den gespeicherten
  Rohdatensatz berechnet und dient der Änderungserkennung. Der Export bereinigt
  Payloads (Credentials, signierte URLs); der Hash ist daher kein
  Prüfwert für den Export.
- **Datenschutz:** Die Löschkategorie `provider_data` kommt hinzu, und die
  Exportformatversion steigt auf 2. Das e2e-Fixture befüllt alle vier Tabellen.

Phase 6.1 (`WorkoutExportPort`) läuft parallel zu Phase 3, weil sie keine
gemeinsamen Dateien berührt. Phase 6.2 folgt nach 6.1.

### 5.9 Ergebnis Phase 6 und Phase 3 Schritt 2

| Einheit | Inhalt | PR |
|---|---|---|
| W8-1 | `WorkoutExportPort`, Intervals-Adapter in `sync/`, REST-Aufrufe im Client | #1101 |
| W8-2 | `PlannedWorkoutExport` (Sport, Umgebung), Intervals-Serialisierer in `providers/intervals_workouts.py` | #1102 |
| W8-3 | Intervals-spezifische Event-Prüfungen aus `planned_calendar.py` in den Adapter | #1104 |
| W6-2 | Dual-Write beim Ingest (Intervals, Garmin), ein Schreibpfad für `garmin_snapshot` | #1103 |

Entscheidungen:

- **Byte-Parität:** Die Intervals-Payload bleibt byte-identisch. Belegt wird
  das durch 3991 Fälle aus `tests/workout_export_parity_matrix.py`, gepinnt per
  Hash, Blockhashes und 51 wörtlichen Stichproben.
- **Adapter-Platzierung:** Der Adapter liegt in `sync/`, weil `providers/`
  nicht `sync/` importieren darf.
- **Gespeicherte Sportwerte:** Sie bleiben im Intervals-Vokabular. Die Planung
  übersetzt sie an der Lesegrenze (`planning/sport.py`).
- **Exakte Typprüfungen:** Für Vorlagen, Ausdauertypen und den
  Readback-Sportabgleich bleiben die Prüfungen auf exakten Typen. Eine
  Umstellung auf `Sport` würde das Verhalten ändern.
- **`steps` im Exportmodell:** Das Exportmodell trägt noch keine `steps`.
  Intervals serialisiert den Text unverändert, und `steps` kommt erst mit einem
  zweiten Ausgabeziel (6.3) hinzu.
- **Löschregel:** Nur ein aktueller, nicht inkrementeller Intervals-Vollabruf
  mit Aktivitätsliste markiert fehlende Aktivitäten als gelöscht. Er tut das nur
  in seinem Fenster und ohne den ersten und letzten Tag, weil Abfragedatum
  (Provider-Ortszeit) und gespeichertes Athletendatum um einen Tag abweichen
  können. Garmin löscht nie, und historische Abrufe löschen nie. Taucht eine
  Aktivität wieder auf, wird sie reaktiviert.
- **Atomarität:** Legacy-Snapshot, kanonische Zeilen und die
  Planabgleich-Reconciliation landen in derselben Transaktion. Die Cursor folgen
  danach. Ungültige Zeilen werden übersprungen und gezählt. Rohpayloads werden
  vor dem Speichern bereinigt (`observability.sanitized_provider_payload`).
- **Abrufzeit je Garmin-Abschnitt:** Jede kanonische Garmin-Zeile trägt die
  Abrufzeit ihres eigenen Abschnitts (`source_freshness`, Morgen-Body-Battery).
  Ein aus einem früheren Abruf erhaltener Abschnitt behält also seine ältere
  Zeit. Die Legacy-Projektion stempelt weiter `synced_at`; die Paritätsprüfung
  in Phase 3 Schritt 5 behandelt diese Abweichung als gewollt.

### 5.10 Ergebnis Phase 3 Schritte 3 und 4

| Einheit | Inhalt | PR |
|---|---|---|
| W6-3 | Backfill aus Legacy-Snapshots und Neuprojektion bei Mapper-Wechsel | #1105 |
| W6-4 | Referenz-Resolver für lokale und alte Provider-IDs, `activity_id` in der API | #1106 |

Entscheidungen:

- **Backfill nur einfügend:** Der Backfill schreibt nur fehlende Zeilen und
  überschreibt nie, was der Dual-Write bereits geschrieben hat. Er arbeitet
  vom neuesten Snapshot zu den älteren. Aktivitäten fügt nur der neueste
  Snapshot ein; ältere Snapshots zählen ihre Aktivitäten als `superseded`.
  Beobachtungen älterer Snapshots werden eingefügt, wenn sie fehlen. Die
  Tabellen können deshalb mehr Beobachtungshistorie enthalten als der neueste
  Snapshot.
- **Wiederaufnahme:** Der Cursor steht in `sync_state` und trägt je Quelle
  einen Fingerprint und einen Offset. Ändert sich die Quelle, beginnt sie bei
  Offset 0. Der Fingerprint der Neuprojektion enthält die Mapper-Version, damit
  ein Versionswechsel mitten im Batch nicht mit altem Offset fortsetzt.
- **Neuprojektion und Tombstones:** Bei einer höheren Mapper-Version werden
  Rohdatensätze neu projiziert. Gelöschte Aktivitätsdatensätze und Datensätze
  gelöschter Sitzungen bleiben erhalten (`preserved`) und werden nicht wieder
  belebt. Aktive und ungültige Zeilen werden aktualisiert. Sitzungsdaten
  ändern sich nur für aktive Sitzungen.
- **Vom Mapper nicht mehr erzeugte Aktivitäten:** Sie werden `invalid`
  (Zähler `retired`). Die Sitzung bleibt unverändert, auch wenn ihr einziger
  Datensatz ungültig ist; der Resolver kann sie dann weiter auflösen.
  Beobachtungen haben in v6 keine Statusspalte und werden nicht stillgelegt.
  Der Tabellenleser liefert deshalb nur Beobachtungen, deren `mapper_version`
  der aktuellen Version ihres Mappers entspricht. Eine Statusspalte für
  Beobachtungen ist ein Kandidat für Phase 7.
- **Alte Garmin-Rohform:** Garmin-Gesundheits-Rohdatensätze in der Form vor
  #1103 werden als `skipped_invalid` gezählt, bis der nächste Garmin-Sync sie
  in aktueller Form schreibt.
- **Resolver:** Er löst `act_`-IDs, alte Provider-IDs und Duplikat-IDs auf.
  Auch die Duplikatlöschung (lokal und als Remote-Write-Vorschlag) löst beide
  IDs vor der Prüfung und dem Freigabemanifest auf. Offener Punkt: `save()`
  kann eine nicht auflösbare `act_`-ID unverändert speichern.
- **Diagnose:** Sie zeigt je Provider nur Zähler (`inserted`,
  `already_present`, `superseded`, `skipped_invalid`, `sessions_created`,
  `duplicates`, `reprojected`, `retired`), keine Athleteninhalte.
- **Qualitätsbaseline:** 460 Einträge gegen `base` `e4d51d75`.

### 5.11 Ergebnis Phase 3 Schritt 5 und Vorbereitung Phase 5

| Einheit | Inhalt | PR |
|---|---|---|
| W6-5 | Tabellenleser für die Leseports mit paritätsgesicherter Umschaltung | #1107 |
| P5-U1 | Paritäts-Ledger: welche Ausgabefelder der kanonische Weg exakt reproduziert | #1108 |
| P5-U2 | Label-Tabelle `providers/source_labels.py` je Ansicht und Provider | #1109 |
| P5-U8 | Legacy-Reader beziehen ihre Provider-Labels aus der Label-Tabelle | #1110 |
| P5-U3 | Kommazahlen im Intervals-Wellness-Mapping (Mapper-Version 3) | #1112 |

Entscheidungen W6-5:

- **Umschaltung nur mit Nachweis:** `CanonicalReadSelector` liefert Aktivitäten
  und Beobachtungen nur dann aus den Tabellen, wenn der Backfill `complete` ist,
  die Paritätsprüfung bestanden hat und ihr Digest noch gilt. Der Digest umfasst
  die aktuellen Mapper-Versionen und die Athletenzeitzone. Jede Mapper-Änderung
  führt deshalb bis zur nächsten Prüfung zurück auf die Legacy-Projektion.
  Coverage kommt immer aus der Legacy-Projektion.
- **Paritätsprüfung:** Sie läuft nach jedem abgeschlossenen Backfill, also bei
  jedem Start. Aktivitäten außerhalb des Legacy-Datumsbereichs ihres Providers
  zählen als Tabellenhistorie, nicht als Abweichung; ohne Legacy-Bereich
  scheitert die Prüfung. Verglichen werden alle Inhaltsfelder, bei Beobachtungen
  zusätzlich Label, `source_kind` und `recorded_by`. Die Garmin-Abrufzeit je
  Abschnitt ist eine gewollte Abweichung und wird ignoriert.
- **Gelieferte Zeilen:** nur aktive Aktivitätsdatensätze nicht gelöschter
  Sitzungen und nur Beobachtungen der aktuellen Mapper-Version.
- **Bekannte Einschränkung:** Der natürliche Schlüssel
  `provider|metric|sport|method|when` kann zwei Werte derselben Metrik am selben
  Tag aus unterschiedlichen Quellen eines Providers nicht halten (z. B.
  Intervals-Wellness- und Athletengewicht). Weichen sie ab, scheitert die
  Paritätsprüfung und die App bleibt auf der Legacy-Projektion. Das ist sicher,
  verhindert aber voraussichtlich die Umschaltung bei echten Daten. Behebung in
  Phase 7: Methodenteil des Schlüssels befüllen und Mapper-Version anheben.

Ergebnis P5-U1 (Ledger über vier synthetische Fälle):

- **Umstellbar ohne Abweichung:** Schwellenpuls Rad/Lauf, VO2max Rad/Lauf,
  Schlafscore, Ruhepuls, Readiness, ATL, Körperfett-Serie.
- **Nur Einheitenunterschied:** Schlafdauer (Sekunden statt Stunden),
  Schwellenpace (m/s statt s/km); umrechnen beim Verbraucher.
- **Kommazahlen:** Gewicht, Gewichtsserie und CTL scheitern an Werten wie
  `"80,4"`, die der Legacy-Weg akzeptiert (P5-U3). CTL gibt der Legacy-Weg
  zusätzlich als Rohtext aus.
- **Bleiben auf Legacy:** Rad-FTP (FTP-Verlauf statt Abschnitt `cycling_ftp`),
  Lauf-Schwellenleistung (Garmin-Laufleistung kanonisch nicht abbildbar),
  Maximalpuls (Rückfall auf Aktivitätswerte), Ruhepuls-Datum beim
  Intervals-Rückfall, Körperfett aus dem Profil.

Ergebnis P5-U2, P5-U8 und P5-U3:

- **Labels:** Alle Provider-Labels der Ansichten kommen aus einer Tabelle; die
  Ausgabe ist bytegleich. Literal bleiben nur Prosa, Wahoo, abgeleitete Werte,
  „Intervals.icu (allgemein)“ in den aktuellen Kennzahlen (nur über
  `observation_source_label` erreichbar, folgt mit U5) und der eFTP-Schlüssel
  „Intervals.icu“ im Körperverlauf.
- **Kommazahlen:** `coerce_comma_decimal_number` liest Text wie die Legacy-Reader
  (jedes Komma als Dezimalpunkt; „1,200“ ist 1,2 wie bisher). Die Anhebung der
  Mapper-Version auf 3 projiziert gespeicherte Rohdaten neu und erzwingt eine neue
  Paritätsprüfung. Gewicht und Gewichtsserie sind damit umstellbar; die CTL-Zeile
  bleibt im Ledger, weil der Legacy-Weg den Rohtext „58,2“ ausgibt. Freigabe
  dieser einen geänderten Ledger-Zeile durch den Koordinator.

Ergebnis P5-U4 (#1111):

- **CTL/ATL:** `/api/performance`, `/api/state` und der Coach lesen CTL und ATL
  aus den kanonischen Beobachtungen (`backend/performance/canonical_inputs.py`),
  ausgewählt über `select_current` für den letzten Wellness-Tag des Snapshots.
  Ohne kanonische Quelle oder ohne gültigen Wellness-Tag läuft der Legacy-Aufruf
  unverändert. Einzige freigegebene Abweichung: Komma-Text „58,2“ wird als
  Zahl 58.2 ausgegeben.
- **Konsistenz:** Snapshot und kanonische Eingaben stammen immer aus einer
  `unit_of_work` (`snapshot_with_inputs`, im State-Prelude `inputs_for_snapshot`).
  Der Coach nutzt kanonische Eingaben nur, wenn er den Snapshot selbst liest.
  Mitgegebene Snapshots behalten die Legacy-Werte.
- **Kompatibilität:** `/api/state` liest das neue Prelude-Feld tolerant, weil
  Testdoubles das Prelude ohne dieses Feld nachbilden.

Ergebnis P5-U5 (#1114):

- **Aktuelle Kennzahlen:** Schwellenpuls Rad/Lauf, VO2max Rad/Lauf und das
  aktuelle Gewicht kommen aus den kanonischen Beobachtungen des Syncs, dessen
  `retrieved_at` dem `synced_at` des Snapshots entspricht
  (`backend/performance/canonical_current.py`). Gewicht: zuerst die Zeile des
  letzten Wellness-Tags, dann der Athletendatensatz; Garmin hat weiter Vorrang,
  das Profil bleibt letzter Rückfall.
- **Eintragsreihenfolge:** Bei mehreren passenden Sport-Einstellungen nimmt der
  Legacy-Reader den ersten Eintrag. Kanonische Beobachtungen tragen keine
  Eintragsidentität, deshalb wird ein kanonischer Kandidat nur genutzt, wenn sein
  Wert dem Legacy-gewählten Wert entspricht; sonst läuft der Legacy-Weg. Kanonisch
  füllt keinen Sportwert auf, den der Legacy-Snapshot leer lässt.
- **Eine Quelle je Abruf:** `read_performance_inputs` wählt die Lesequelle einmal
  (`reader_for`, #1116) für Last- und Kennzahlen-Reads.
- **Offen:** naives `synced_at` und Snapshots ohne nutzbare Wellness-Zeile behalten
  die Legacy-Werte; Typklassifikation der Sport-Einstellungen (`types[0]` im Mapper
  gegenüber Teilstring-Suche im Legacy-Reader) wird in Phase 7 angeglichen.

Ergebnis P5-U7 (#1115):

- **Körperverlauf:** Gewichts- und Körperfettverlauf (Intervals und Garmin) für
  `/api/performance` und die Analyse-Historie kommen aus kanonischen Beobachtungen
  (`backend/performance/canonical_body.py`), Werte, Daten und `synced_at` wie im
  Legacy-Verlauf. Garmin-Messungen eines Tages werden wie im Legacy-Reader
  geordnet: ohne Zeit zuerst, sonst nach UTC-Zeitpunkt.
- **Konsistenz:** `performance_state()` liest Leistungs-Snapshot, Garmin-Snapshot
  und alle kanonischen Eingaben in einer `unit_of_work` und wählt die Lesequelle
  einmal (`resolve_reader`).
- **Offen (Phase 7):** `/api/state` und `coach/activity_read_tools.py` lesen den
  Körperverlauf noch über Legacy; Gleichstände untimed Garmin-Messungen folgen der
  kanonischen statt der Traversierungsreihenfolge.

Ergebnis P5-U6 (#1121):

- **Erholungswerte:** `sleep_score`, `resting_hr` und `readiness` im
  Erholungskontext kommen aus kanonischen Beobachtungen
  (`backend/performance/canonical_recovery.py`). Ein Kandidat wird nur genutzt,
  wenn Provider, Tag und Wert dem Legacy-gewählten Datensatz entsprechen; sonst
  bleibt der Legacy-Wert. Labels bleiben die Legacy-Texte.
- **Nicht umgestellt:** `resting_hr_date`, `sleep_hours` und HRV (Ledger
  `switchable: false`), `personal_recovery.py`, `planning_recovery.py` und die
  Garmin-Projektion.
- **Offen (Phase 7):** Recovery-Ansicht in `source_labels`, kanonische
  persönliche und Planungs-Erholung; pro Abruf drei zusätzliche Lesezugriffe.

Aufteilung Phase 5 (Stufen):

| Stufe | Einheiten |
|---|---|
| 0 | U1 Ledger, U2 Label-Tabelle `providers/source_labels.py`, U3 Kommazahlen im Intervals-Mapping |
| 1 | U4 CTL/ATL, U5 aktuelle Kennzahlen über `select_current`, U6 Erholung über `select_daily`, U7 Gewichts- und Körperfettverlauf |
| 2 | U8 Aktivitäts- und Planungslabels aus der Label-Tabelle |
| 3 | U9 PWA: Provider und Labels aus dem Bootstrap statt Labelvergleichen |
| 4 | U10 Coach-Kontext nach Fachbereich |

Regel: Die Legacy-Builder bleiben das Orakel. Verbraucher erhalten kanonische
Eingaben über einen optionalen Parameter; ohne ihn läuft der Legacy-Weg, und die
Charakterisierungstests bleiben unverändert. Nach Phase 7 verschoben, weil das
kanonische Modell sie nicht abbildet: eFTP, TSB/Form, Rampenrate, W′,
Rennprognosen, Trainingsstatus, HRV-Wochenmittel, Aktivitätslisten und -details,
Energieverbrauch, Ausrüstung, FTP-Verlauf und Freshness aus `retrieved_at`.

### 5.12 Ergebnis Phase 5 Stufen 3–4 und Phase 7 (alle gemergt, Stand 2026-10-12)

| Einheit | PR | Inhalt |
|---|---|---|
| P5-U9 | #1127 | PWA filtert und gestaltet Kennzahlen über `source_provider` statt Labelvergleich; Fallbacks für W/kg-Punkte und nicht zugeordnete Kennzahlen bleiben |
| P5-U10 | #1122 | Strukturierter Coach-Kontext nach Fachbereich statt nach Provider gruppiert |
| P7-A | #1125 | Trainingslast der Saisonvorbereitung aus kanonischen Beobachtungen (`canonical_season_load.py`) |
| P7-D | #1124 | Tests für kanonische Eingaben im Coach-Werkzeug für Aktivitätsdetails |
| P7-B | #1126 | Planungs- und Tageserholung kanonisch; Garmin-Snapshot-Parser fängt `RecursionError` ab |
| P7-F | #1123 | Gespeicherte Wettkampf-Sportarten über `COMPETITION_SPORT_TOKENS` in kanonische `Sport` übersetzt |
| P7-C | #1128 | 7-Tage-Mittel von Ruhepuls und Readiness aus kanonischen Beobachtungen (`canonical_recovery_averages.py`), nur bei gleicher Tagesmenge und gleichem gerundetem Mittel |
| P7-E | #1129 | Persönliche Erholung: Ruhepuls je Provider und Tag kanonisch (`canonical_personal_recovery.py`); Labels laufen bereits über `ProviderId` und `DAILY_HEALTH`, eine eigene Label-Ansicht war nicht mehr nötig |
| P7-G | #1130 | Schema v7: nullable `provider` in `activity_feedback`, gesetzt nur bei über eine lokale Sitzung aufgelöster `act_`-ID; Bestandszeilen bleiben NULL; Datenschutz-Export Formatversion 3 enthält die Spalte |

Gemeinsame Regel wie in Phase 5: kanonische Werte nur, wenn Provider, Tag und
Wert dem Legacy-Datensatz entsprechen; ohne `canonical=` läuft der Legacy-Weg.

Entscheidungen vom 2026-10-12 (Nutzerfreigabe):

- **Rückbau Option 1:** Legacy-Leser, Paritätsprüfungen und Dual-Write werden
  entfernt; alle Leser nutzen nur die kanonischen Tabellen. Es wird nichts
  gelöscht: `snapshots` und `garmin_snapshot` bleiben eingefroren erhalten und
  erhalten nur noch Sync-Metadaten und Zustandsdaten. Die Snapshot-Reduktion
  (Löschen nach verifiziertem Nachweis) bleibt ein späterer, eigener Schritt.
- **Phase 8 (Wahoo):** API-Zugang (`WAHOO_CLIENT_ID`/`WAHOO_CLIENT_SECRET`) liegt
  vor, Nutzungsbedingungen sind geklärt. Umfang: Workouts/Aktivitäten lesen und
  Pläne an Wahoo senden. Login per OAuth-Autorisierungscode aus der PWA; Tokens
  verschlüsselt in der Datenbank. Damit ist Wahoo das zweite Ausgabeziel, und
  Phase 6.3 (`remote_links`) ist beauftragt.

### 5.13 Plan Rückbau (Option 1), Phase 6.3 und Phase 8 (ab 2026-10-12)

Bestandsaufnahme: Der Leistungsabruf (`sync/performance.py`) schreibt nur in
den Snapshot; die Abdeckung (`CanonicalReadSelector.coverage`) liest nur
Legacy. Nicht kanonisierbare Zustandsdaten (Intervals-Kalender, Leistungsprofil,
Paginierung, `historical_sync`; Garmin `source_freshness`, Morgen-Body-Battery,
`errors`, Ausrüstung, nicht gemappte Abschnitte) bleiben im Snapshot. Der
Rückbau entfernt daher aus neuen Snapshots nur die kanonisierten Abschnitte
(Aktivitäten, Wellness, gemappte Gesundheitswerte); die Snapshot-Zeilen bleiben
als Sync-Metadaten und Zustand bestehen. v7 ist unveröffentlicht (1.12.32 hat
v6); `remote_links` wird v8, v7 wird als develop-Form eingefroren.

| Spur | Einheit | Inhalt | hängt ab von |
|---|---|---|---|
| R | R1 | Kanonischer Ingest des Leistungsabrufs, Abdeckung persistiert, Backfill vor dem Lesen abgeschlossen | – |
| R | R2 | Selektor bedient Tabellen nach abgeschlossenem Backfill ohne Paritätsbedingung | R1 |
| R | R3–R7 | Leser je Domäne nur kanonisch (Leistung, Planung, Aktivitäten, Coach/HTTP, Garmin-Zustand) | R2 |
| R | R8 | Paritäts-Infrastruktur und -Tests entfernen | R3–R7 |
| R | R9 | Kanonisierte Abschnitte nicht mehr in Snapshots schreiben | R8 |
| R | R10 | Gespeicherte Sportwerte auf `Sport` umschreiben (eigene Schemaversion), Kopplungs-Baseline leeren | S1, R9 |
| R | R11 | Workout-Sportvokabular hinter `canonical/stored_sports.py`, Dubletten entfernen | – |
| S | S1 | Schema v8: `remote_links`, Providerspalte der Tombstones, Backfill aus Einzel-Slots, Export Version 4 | – |
| S | S2 | Remote-IDs lesen und schreiben über `remote_links` | S1 |
| S | S3 | Bibliotheks-Sync über `WorkoutExportPort` | S2 |
| W | W1 | Wahoo-Konfiguration, OAuth-Verbindung aus der PWA, Token-Speicher in der DB, Redaktion | – |
| W | W2 | Wahoo-Client, Mapper, Ingest-Plan, Deskriptor, Laufzeit-Registrierung | W1 |
| W | W3 | Persistierte Sitzungsbündelung (Intervals, Garmin, Wahoo) | W2 |
| W | W4 | Wahoo-`WorkoutExportPort` für Pläne, ausdrücklicher Sync mit Ziel aus dem Register | S3, W2 |
| W | W5 | PWA: Verbinden, Status, Labels; README | W1, W2 |

### 5.14 Ergebnis Rückbau R10 (alle gemergt, Stand 2026-10-13)

| Einheit | PR | Inhalt |
|---|---|---|
| R10a | #1156 | Schema v9: gespeicherte Sportwerte als `Sport`/`Environment`, transaktionale Migration v8 → v9, Export Version 5 |
| R10c | #1152 | Leistung liest Providerfelder über Adapter statt Wire-Namen |
| R10e | #1157 | Planung und Coach lesen Providerfelder über Adapter |
| R10f | #1158 | Sync liest Providerfelder über Adapter |
| R10d | #1159 | Aktivitäten, Athlet, Kalender und Diagnose über Adapter; Fehlerlabels in `canonical/labels.py` (zyklenfrei) |
| R10b | #1160 | HTTP/PWA: neutrale Metriknamen (`training_load`, `intensity`, `rpe`) nur an der Browser-Grenze, Provider-IDs aus dem Bootstrap |
| R10g | #1161 | Resync-Gates aus den Deskriptoren; Kopplungs-Baseline leer |

Befunde aus dem Review von #1160: `PublicPlanStateService.read` bleibt für
Trainingsbericht und Saisonszenarien bei den gespeicherten Schlüsseln; nur
`read_public` (`/api/plan`), `/api/activities`, Bootstrap-Aktivitäten und
Runden (`laps`) übersetzen. Der Kopplungs-Guard verweigert eine leere
Baseline weiterhin ohne Scan oder ohne bestehende Baseline und erlaubt sie
nur, wenn alle bestehenden Einträge nach einem echten Scan entfernt sind.

## 6. Pflichtnachweise für Schema-PRs (v6 und folgende)

- Eingefrorenes Fixture des zuletzt veröffentlichten Schemas mit Daten; direkte
  Upgrades von v1, v2, v3, v4 und v5 einschließlich übersprungener Releases, mit
  befüllten Tabellen (`seed_all_tables` in `tests/test_db_migrations.py`).
- Rollback bei Fehlern in jedem Schritt, Same-Build-Restart und Abweisung
  unbekannter oder neuerer Versionen ohne Datenänderung (der bestehende Test mit
  `(None, 5, 6, 99)` wird auf die neue Version angepasst).
- SQLCipher-Wiederöffnung in Docker/CI, da kein Windows-Wheel existiert.
- Restore älterer Backups einschließlich Migration sowie Rollback der
  Restore-Validierung.
- Datenschutz: neue Tabellen in `PRIVACY_EXPORT_JSONL_FILES` bzw. den expliziten
  SELECTs in `backend/backup/export.py` und in `PRIVACY_DELETE_SCOPE` in
  `backend/privacy.py`; Tabellenmengen-Test in `tests/test_server_database.py`.
  Providerdaten und vom Athleten verfasste Daten (Feedback, Ausrüstungszuordnung)
  sind getrennte Löschkategorien. Ein erneuter Import nach dem Löschen der
  Providerdaten erzeugt nur Aufzeichnungen und keine Athletendaten. Eine
  vollständige Löschung entfernt beide. Der Export enthält keine Tokens,
  Authorization-Header oder signierten URLs; `PRIVACY_EXPORT_FORMAT_VERSION`
  wird erhöht, wenn sich die Dateiliste ändert.
- e2e-Standard-Fixture (`e2e/fixture_runtime.py`) befüllt die neuen Tabellen;
  `e2e/test_fixture_standard_data.py` deckt das ab.
- README und Dokumentation bei sichtbarem Verhalten. Eine leere Datenbank ist
  kein Upgrade-Nachweis.

## 7. Wahoo als Abnahmefall

Die öffentliche Dokumentation der Wahoo Cloud API (Stand Oktober 2026) nennt:

- OAuth 2.0 (Authorization Code, optional PKCE, Refresh-Tokens). Scopes u. a.
  `user_read`, `workouts_read`, `workouts_write`, `plans_read`, `plans_write`,
  `power_zones_read` und `offline_data`.
- Endpunkte für Workouts mit Workout-Summary und FIT-Datei, strukturierte Pläne
  (`/v1/plans`) und Power-Zonen. Schlaf-, HRV- und Erholungsdaten gibt es nicht.
- Den API-Zugang muss man bei Wahoo beantragen. Sandbox- und Produktions-Apps
  sind getrennt, und die Sandbox ist stark gedrosselt.
- Webhooks setzen einen öffentlich erreichbaren Endpunkt voraus. Das ist mit dem
  LAN/VPN-Betrieb nicht vereinbar; die App nutzt daher ausschließlich Polling.

Folgen:

- Die Intervals-Daten enthalten bereits Wahoo-Aufzeichnungen (Herkunft `wahoo`).
  Ein direkter Wahoo-Import liefert dieselben Einheiten ein zweites Mal; ohne
  Sitzungsbündelung entstünden Dubletten. Der fachliche Mehrwert liegt
  voraussichtlich im **Outbound** (strukturierte Pläne auf ELEMNT/KICKR) und in
  den Power-Zonen. Damit wird Phase 6 einschließlich `remote_links`
  Voraussetzung.
- Authentifizierung über einen einmaligen Login-Helfer analog
  `garmin-login.py`. Tokens bleiben serverseitig, verschlüsselt in der
  SQLCipher-Datenbank statt in einer Klartextdatei, und erscheinen nie in Logs,
  Diagnose, Export oder Coach-Kontext.
- FIT-Dateien bräuchten einen Parser als neue Abhängigkeit (Pin in
  `requirements.in`, Hash-Lock, Docker-Build, Python 3.14) – nur falls Details
  aus Wahoo statt aus Intervals benötigt werden.
- Rate-Limits über Backoff und Capability-Pause wie bei Garmin
  (`garmin_capability_*`), konfiguriert im Deskriptor.

Abnahmekriterium des Gesamtvorhabens: Wahoo erfordert nur `providers/wahoo.py`,
`providers/wahoo_mapping.py`, den Deskriptor, die Registrierung mit Job-Owner,
die Verdrahtung in `server.py`, `.env.example` und README, den Login-Helfer sowie
Fixtures und Tests. In `performance/`, `activities/`, `planning/`, `coach/`,
`http_api/` und `public/` ist höchstens ein Präzedenzeintrag nötig.

## 8. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
| --- | --- |
| Stille Abweichungen abgeleiteter Werte | Zuerst charakterisieren, Paritätstests in jedem PR, Umstellung je Domäne |
| Datenverlust oder fehlerhaftes Upgrade | v6 rein additiv, Backfill als idempotenter Job außerhalb der Migration, Rückbau erst nach verifiziertem Backfill, Nachweise aus Abschnitt 6 |
| Speicherwachstum durch Rohdaten | Ersetzt 12 Vollkopien und unbegrenztes `raw_provider_data`; Aufbewahrungsregel je Datenart (Entscheidung 1) |
| Verwaiste Referenzen durch neue IDs | API-`id` und Speicherschlüssel bleiben Provider-IDs, Resolver für alte und neue IDs, unveränderte Analyse-Fingerprints, Zähler für nicht auflösbare Referenzen |
| Lücken durch nicht atomaren Dual-Write | Kanonische Daten und Snapshot in einer Transaktion, Cursor zuletzt, Fehlerinjektionstest |
| Remote gelöschte Aktivitäten bleiben stehen | Löschmarkierung nur bei vollständig abgerufenem Fenster, nie physisches Löschen lokaler Historie |
| Leistung auf SQLCipher | Typisierte Spalten, Indizes auf `local_date`, `provider` und `metric`, begrenzte Abfragen, Messung im Docker-Fixture |
| Nicht vergleichbare Lastmodelle | `LoadModel` am Wert; die Policy verbietet Mischreihen |
| Zeitzonen und naive Ortszeiten | `start_utc` plus Athleten-Zeitzone; Mapper-Tests mit Sommerzeitwechsel |
| Coach-Qualität nach Kontextumbau | Eigener PR, Evaluationsfälle, Budget-Tests |
| Überentwicklung | Nur Felder mit konkretem Verbraucher; kein generisches Entity-Framework (A1) |
| Zwei Schreiber auf `garmin_snapshot` | Geprüft: beide Pfade teilen `GARMIN_SYNC_LOCK`; ein Identitätstest (Phase 0.5) sichert das bis zum einzigen Schreibpfad über Ingest (Phase 3) |
| Wahoo-Zugang und Nutzungsbedingungen | Vor Phase 8 klären; ohne Freigabe endet das Vorhaben nach Phase 7 trotzdem mit providerneutraler Architektur |

## 9. Entscheidungen

Die ursprünglich offenen Punkte sind entschieden (Oktober 2026):

1. **Aufbewahrung von Rohdaten:** Zusammenfassungen unbegrenzt (klein,
   ermöglichen Neuprojektion); Streams weiterhin nur bei Bedarf und begrenzt.
2. **Wahoo-Zielbild:** zuerst inbound (Workouts und Leistungszonen, Bündelung
   mit Kopien in Intervals.icu). Seit 2026-10-12 ist zusätzlich Outbound
   (Pläne an Wahoo) beauftragt; damit wird Phase 6.3 umgesetzt.
3. **Präzedenz:** fest im Code (`SourcePolicy`); eine Athleteneinstellung erst
   bei konkretem Bedarf.
4. **Coach-Kontext:** nach Fachbereichen statt nach Providern, als eigener PR
   mit Evaluation.
5. **Basisversion für v6:** v5 ist seit 1.12.29 veröffentlicht (auch 1.12.30
   und 1.12.31). W5-1 friert es aus 1.12.31 als Fixture ein; v6 setzt darauf auf.
6. **Entfernen eines Providers:** deaktivieren statt löschen. Die gespeicherten
   Aufzeichnungen und Observations bleiben erhalten und lesbar; die Präzedenz
   überspringt den Provider für neue Werte, und das Höchstalter je Kennzahl
   markiert verbliebene Werte als veraltet. Zusammengeführte Sitzungen behalten
   ihre Primäraufzeichnung. Endgültiges Löschen nur über den
   Datenschutz-Löschpfad (eigene Kategorie Providerdaten). Die Provider-ID
   bleibt reserviert, damit eine Wiederverbindung dieselben Datensätze
   fortschreibt.

## 10. Definition of Done

- Guard-Baseline leer: keine Provider-Feldnamen außerhalb von
  `backend/providers/`, keine Providernamen-Literale außerhalb von Register,
  Mappern, Verdrahtung und Migrationen.
- Ein gemockter Test-Provider mit Aktivitäten und Observations erscheint in
  Analyse, Plan-Kalender, Coach-Kontext, Freshness und Datenschutz-Export ohne
  Codeänderung in Domäne, HTTP oder PWA.
- Alle Präzedenzregeln stehen in einer Tabelle und sind durch Tests belegt;
  jeder Wert trägt Quelle, Messzeit und Abrufzeit.
- Bestehende Installationen mit v1–v5 aktualisieren datenbewahrend;
  Backup/Restore, Same-Build-Restart, Export und Löschung sind abgedeckt.
- Vorhandenes Feedback, Detailanalysen, Ausrüstungszuordnungen, alte
  Paginierungscursor und Aktivitäts-IDs im Coach-Verlauf bleiben auflösbar.
- Ein unterbrochener Backfill läuft ohne Dubletten weiter; ein Persistenz- oder
  Providerfehler setzt keinen Cursor weiter.
- Ohne Provider-Sync bleibt die zuletzt lokal gespeicherte Sicht lesbar.
- Dokumentation aktualisiert: README (Provider-Konfiguration),
  `docs/api-routes.md` bei Routenänderungen und `docs/workout-export-format.md`
  (internes Format gegenüber den Serialisierern).
