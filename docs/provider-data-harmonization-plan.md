# Plan: Providerunabhängiges Datenformat für Trainings- und Gesundheitsdaten

Stand: 9. Oktober 2026. Grundlage ist Commit `3f8bcaaa` auf `develop`
(`APP_VERSION` 1.12.27, `CURRENT_SCHEMA_VERSION = 4`; letztes Release-Tag 1.12.26
mit Schema v3). Status: Plan, noch keine Umsetzung.

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

`performance/personal_recovery.py:45` verwendet Intervals-HRV nur bei
`hrv_method` `RMSSD` oder `SDNN`. `performance/context.py:61` und `:124`
übergeben jedoch die kompakte `recent_wellness`-Liste, die
`planning/context.py:284` über `WELLNESS_FIELDS` filtert – und dort fehlt
`hrv_method`. Nur Tests und das e2e-Fixture liefern das Feld. Empfehlung: ein
kleiner `fix(performance)`-PR vorab mit Regressionstest über den echten
Produzenten-/Verbraucherpfad. Das kanonische Format behebt diese Fehlerklasse
später strukturell.

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

### 3.4 Persistenz (Schema v5, additiv)

Skizze; die endgültige DDL entsteht im Persistenz-PR.

| Tabelle | Zweck | Schlüssel |
| --- | --- | --- |
| `provider_records` | Unveränderte, untrusted Wire-Datensätze für Provenienz und Neuprojektion; `payload_hash`, `fetched_at`, `mapped_version` | `(provider, kind, provider_record_id)` |
| `activity_records` | Kanonische Aufzeichnungen; typisierte Spalten für Abfragen (Sport, `local_date`, Dauer, Distanz, Last …), validiertes kanonisches JSON (z. B. Zonenzeiten), Aufzeichnungszustand | eindeutig `(provider, provider_activity_id)`; Verweis auf `activity_sessions.activity_id` |
| `activity_sessions` | Bündelung, Primäraufzeichnung, Verknüpfungsart, Athletenbestätigung, Sichtbarkeit; zusammengeführte Sitzungen bleiben mit `merged_into` erhalten | opake, stabile `activity_id` |
| `observations` | Tages- und Punktwerte im Langformat | eindeutig je `(provider, metric, sport, method, observed_at bzw. local_date)` |

Bestehende Tabellen und kv-Einträge (`snapshots`, `garmin_snapshot`,
`activity_detail:*`, `equipment_assignment:*`, Ausrüstung) bleiben in v5
unverändert und werden weiter geschrieben (Dual-Write). Referenzen werden nicht
umgeschlüsselt, sondern über einen Resolver aufgelöst: lokale `activity_id` →
Primäraufzeichnung bzw. alte Provider-ID → `(provider, provider_activity_id)` →
Sitzung. Für `activity_feedback` ist keine Schemaänderung nötig, weil die
bestehenden IDs Intervals-IDs aus der Aktivitätsliste sind; der Backfill prüft
das und zählt nicht auflösbare Feedbackzeilen, die erhalten bleiben. Eine
Providerspalte folgt erst mit dem Rückbau. Die Cursor in `provider_sync_cursors`
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
4. **Migrationsgerüst:** eingefrorene Schemasignaturen je Version statt
   Rückrechnung aus dem aktuellen Schema und eine registrierte Schrittkette
   `v1 → v2 → v3 → v4 → …`; verhaltensgleich, bestehende Migrationstests bleiben
   grün. Nach dem Release von 1.12.27 das Fixture `schema_1_12_27.sql.txt` (v4)
   einfrieren.

Abnahme: volle Suite, Qualitäts-Ratchet ohne neue Befunde. Größe: mittel.

### Phase 1 – Kanonischer Vertrag und Mapper

1. `backend/canonical/` mit Vokabular, Datensätzen und Validierung von Einheiten
   und Wertebereichen; Registrierung im Layer-Test.
2. `providers/intervals_mapping.py` und `providers/garmin_mapping.py`: reine
   Funktionen mit `MAPPER_VERSION`. Sie bündeln die verstreuten
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

### Phase 3 – Kanonische Persistenz und Aktivitätsidentität (Schema v5)

Kommt vor der Verbraucherumstellung, weil Feedback, Ausrüstung, Analysen,
Paginierung und Coach-Werkzeuge stabile IDs brauchen, sobald sie kanonische
Aktivitäten verwenden.

1. Migration v5 (additiv) mit allen Nachweisen aus Abschnitt 6.
2. Ingest-Schreibpfad nach Abschnitt 3.4: Intervals- und Garmin-Jobs schreiben
   Rohdatensätze, kanonische Datensätze und den Legacy-Snapshot in derselben
   Transaktion (Dual-Write), Cursor zuletzt. `garmin_snapshot` erhält genau einen
   Schreibpfad; heute schreiben Sync und Morgen-Body-Battery getrennt.
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

### Phase 4 – Provider-Register und Orchestrierung

Umsetzung nach Abschnitt 3.6. Kann nach Phase 1 parallel zu den Phasen 2, 3 und
5 laufen.

Abnahme: Ein nur in Tests registrierter, gemockter Provider durchläuft
Zeitplanung, Queue, Ausführung, Freshness, Status, HTTP-Status und Coach-Refresh
ohne Änderungen außerhalb seiner Registrierung. Größe: mittel bis groß.

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
| 0.1 HRV-Fix | – | `fix(performance): keep Intervals HRV method for personal baselines` |
| 0.2–0.3 Fixtures, Charakterisierung | – | `test(performance): characterize provider source precedence` |
| 0.4 Migrationsgerüst | – | `refactor(db): register frozen schema signatures per version` |
| 1 Vertrag, Mapper, Guard | 0.2–0.3 | `feat(canonical): add provider-independent records and mappers` |
| 2 Leseschicht | 1 | `refactor(sync): read provider snapshots through canonical ports` |
| 3 Persistenz v5, Identität | 0.4, 2 | `feat(db): persist canonical provider records in schema v5` |
| 4 Register | 1 | `refactor(sync): drive provider orchestration from a registry` |
| 5 Verbraucher | 3 | `refactor(performance): consume canonical observations` |
| 6 Outbound | 4 | `refactor(planning): export workouts through a provider port` |
| 7 Rückbau | 3, 5 | `refactor(sync): remove legacy provider snapshot reads` |
| 8 Wahoo | 3, 4, 5; bei Outbound auch 6 | `feat(providers): add Wahoo provider` |

Kritischer Pfad bis „neuer Provider ohne Domänenänderung“: 0 → 1 → 2 → 3 → 5,
mit 4 parallel.

## 6. Pflichtnachweise für Schema-PRs (v5 und folgende)

- Eingefrorenes Fixture des zuletzt veröffentlichten Schemas mit Daten; direkte
  Upgrades von v1, v2, v3 und v4 einschließlich übersprungener Releases, mit
  befüllten Tabellen (`seed_all_tables` in `tests/test_db_migrations.py`).
- Rollback bei Fehlern in jedem Schritt, Same-Build-Restart und Abweisung
  unbekannter oder neuerer Versionen ohne Datenänderung (der bestehende Test mit
  `(None, 5, 99)` wird auf die neue Version angepasst).
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
| Datenverlust oder fehlerhaftes Upgrade | v5 rein additiv, Backfill als idempotenter Job außerhalb der Migration, Rückbau erst nach verifiziertem Backfill, Nachweise aus Abschnitt 6 |
| Speicherwachstum durch Rohdaten | Ersetzt 12 Vollkopien und unbegrenztes `raw_provider_data`; Aufbewahrungsregel je Datenart (Entscheidung 1) |
| Verwaiste Referenzen durch neue IDs | API-`id` und Speicherschlüssel bleiben Provider-IDs, Resolver für alte und neue IDs, unveränderte Analyse-Fingerprints, Zähler für nicht auflösbare Referenzen |
| Lücken durch nicht atomaren Dual-Write | Kanonische Daten und Snapshot in einer Transaktion, Cursor zuletzt, Fehlerinjektionstest |
| Remote gelöschte Aktivitäten bleiben stehen | Löschmarkierung nur bei vollständig abgerufenem Fenster, nie physisches Löschen lokaler Historie |
| Leistung auf SQLCipher | Typisierte Spalten, Indizes auf `local_date`, `provider` und `metric`, begrenzte Abfragen, Messung im Docker-Fixture |
| Nicht vergleichbare Lastmodelle | `LoadModel` am Wert; die Policy verbietet Mischreihen |
| Zeitzonen und naive Ortszeiten | `start_utc` plus Athleten-Zeitzone; Mapper-Tests mit Sommerzeitwechsel |
| Coach-Qualität nach Kontextumbau | Eigener PR, Evaluationsfälle, Budget-Tests |
| Überentwicklung | Nur Felder mit konkretem Verbraucher; kein generisches Entity-Framework (A1) |
| Zwei Schreiber auf `garmin_snapshot` | Ingest als einziger Schreibpfad (Phase 3); die Lock-Nutzung des Morgen-Pfads ist bis dahin nicht verifiziert und wird in Phase 0 geprüft |
| Wahoo-Zugang und Nutzungsbedingungen | Vor Phase 8 klären; ohne Freigabe endet das Vorhaben nach Phase 7 trotzdem mit providerneutraler Architektur |

## 9. Offene Entscheidungen

1. **Aufbewahrung von Rohdaten.** Empfehlung: Zusammenfassungen unbegrenzt (klein,
   ermöglichen Neuprojektion), Streams weiterhin nur bei Bedarf und begrenzt.
2. **Wahoo-Zielbild:** Inbound, Outbound oder beides. Empfehlung: Outbound zuerst
   prüfen, weil es bestimmt, ob Phase 6.3 vor Phase 8 nötig ist.
3. **Konfigurierbare Präzedenz.** Empfehlung: fest im Code; eine
   Athleteneinstellung erst bei konkretem Bedarf.
4. **Coach-Kontext nach Fachbereichen statt nach Providern.** Empfehlung: ja, als
   eigener PR mit Evaluation.
5. **Basisversion für v5.** v5 setzt auf das veröffentlichte v4 (1.12.27) auf;
   das Fixture wird nach dem Release eingefroren.

## 10. Definition of Done

- Guard-Baseline leer: keine Provider-Feldnamen außerhalb von
  `backend/providers/`, keine Providernamen-Literale außerhalb von Register,
  Mappern, Verdrahtung und Migrationen.
- Ein gemockter Test-Provider mit Aktivitäten und Observations erscheint in
  Analyse, Plan-Kalender, Coach-Kontext, Freshness und Datenschutz-Export ohne
  Codeänderung in Domäne, HTTP oder PWA.
- Alle Präzedenzregeln stehen in einer Tabelle und sind durch Tests belegt;
  jeder Wert trägt Quelle, Messzeit und Abrufzeit.
- Bestehende Installationen mit v1–v4 aktualisieren datenbewahrend;
  Backup/Restore, Same-Build-Restart, Export und Löschung sind abgedeckt.
- Vorhandenes Feedback, Detailanalysen, Ausrüstungszuordnungen, alte
  Paginierungscursor und Aktivitäts-IDs im Coach-Verlauf bleiben auflösbar.
- Ein unterbrochener Backfill läuft ohne Dubletten weiter; ein Persistenz- oder
  Providerfehler setzt keinen Cursor weiter.
- Ohne Provider-Sync bleibt die zuletzt lokal gespeicherte Sicht lesbar.
- Dokumentation aktualisiert: README (Provider-Konfiguration),
  `docs/api-routes.md` bei Routenänderungen und `docs/workout-export-format.md`
  (internes Format gegenüber den Serialisierern).
