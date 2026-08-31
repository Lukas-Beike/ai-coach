# Vollständiger Application Review – Intervals Coach

**Prüfstand:** `origin/develop` @ `54f60b7`
**Prüfdatum:** 31. August 2026
**Scope:** Backend, Browser/PWA, Datenmodell, Synchronisation, Coach-Kontext und -Werkzeuge, externe Anbindungen, Security/Privacy, Betrieb, Tests und Informationsarchitektur

## 1. Kurzfazit

Intervals Coach hat für seinen bewusst engen Einsatzbereich – eine einzelne Person in einem vertrauenswürdigen LAN/VPN – eine ungewöhnlich solide Sicherheits- und Datenbasis. Besonders positiv sind SQLCipher als harte Startvoraussetzung, serverseitige Credentials, CSRF- und Session-Schutz, sichere Markdown-Ausgabe, Herkunftskennzeichnungen, begrenzte Provider-Requests, SSRF-Schutz für iCalendar sowie Vorschau-/Fingerprint-Mechanismen bei adaptiver Planung.

Der wichtigste Handlungsbedarf liegt nicht in fehlenden Features, sondern in der **Zustimmungs- und Mutationslogik**. Drei Pfade können die Erwartung „erst nach ausdrücklicher Freigabe schreiben“ verletzen:

1. Negierte oder rein erklärende Chat-Sätze können durch Schlüsselworterkennung als Änderungsauftrag klassifiziert werden.
2. Eine normale Intervals-Synchronisation synchronisiert zugleich lokale Bibliothekseinträge nach Intervals.icu.
3. Start- und Tagessynchronisationen können ausstehende Wettkampfänderungen zu Intervals.icu übertragen.

Damit können lokale oder entfernte Änderungen ohne die Freigabe erfolgen, die UI, README und Architekturgrenzen versprechen. Diese Punkte sollten vor weiterer Feature-Arbeit behoben werden.

Weitere Hauptthemen sind eine bereits im leeren Zustand relativ langsame, stark gekoppelte State-Antwort, ungebremstes Wachstum bei „gesamte Historie“, zwei reproduzierbare CSS-Fehler bei versteckten Elementen, ein überladener Tab „Geplant“, fehlende Browser-/Accessibility-Tests sowie die hohe Wartungslast der beiden Monolithen `server.py` und `public/app.js`.

### Prioritäten auf einen Blick

| Priorität | ID | Befund | Wirkung |
|---|---|---|---|
| **Kritisch** | COACH-01 | Negationsblinde Freigabe mutierender Coach-Werkzeuge | Unerwünschte lokale oder entfernte Änderungen |
| **Kritisch** | SYNC-01 | Normale Intervals-Synchronisation schreibt implizit die Workout-Bibliothek remote | Verletzt die explizite Sync-Grenze |
| **Hoch** | SYNC-02 | Start-/Tagessync kann ausstehende Wettkampfänderungen remote schreiben | Verletzt die explizite Sync-Grenze |
| **Hoch** | DATA-01 | Dialog „Lokale Daten löschen“ nennt nur einen Teil der tatsächlich gelöschten Daten | Irreversibler Datenverlust bei unvollständiger Aufklärung |
| **Hoch** | PERF-01 | Gesamthistorie und vollständiger UI-State sind praktisch unbeschränkt | Wachsende Ladezeit, Speicher- und Browserlast |
| **Hoch** | COACH-02 | Geplante Workouts werden umfangreich und doppelt in den Coach-Kontext serialisiert | Tokenkosten, Latenz, mögliche Kontextverdrängung |
| **Hoch** | SEC-01 | Log-Redaktion berücksichtigt Garmin-E-Mail und private Kalender-URL nicht | Potenzieller Credential-/Identitätsabfluss in Fehlerlogs |

## 2. Vorgehen, zusätzliche Kategorien und Grenzen

Vor Beginn wurden die vom Auftrag genannten Bereiche um folgende sinnvolle Kategorien ergänzt:

- Accessibility und mobile Bedienbarkeit
- Datenschutz und Datenlebenszyklus
- Datenintegrität, Backup und Wiederherstellung
- Fehlerbehandlung und Recovery
- Testbarkeit und Qualitätsabsicherung
- Betrieb, Deployment und Observability
- Wartbarkeit und technische Schulden
- PWA-/Offline-Verhalten
- Transparenz, Zustimmung und Vertrauen

Die Prüfung umfasste:

- vollständige statische Sichtung des Python-Backends, des PWA-Frontends, der Tests, Workflows, Dokumentation und Containerdefinition;
- Syntaxprüfung mit `python -m py_compile`;
- kompletten Unit-Test-Lauf im SQLCipher-Container;
- reproduzierbaren Docker-Build des geprüften `develop`-Stands;
- isolierten Laufzeit- und Browser-Smoke-Test in Chromium auf 390 × 844 und 1440 × 1000 Pixeln;
- Prüfung aller sechs Tabs, Login, responsive Breiten, Console-/Page-Errors, State-Antwortzeiten und Asset-Auslieferung;
- einen Dependency-Audit der Python-Pakete;
- gezielte Prüfung kritischer Zustimmungs-, Sync-, Restore-, Logging- und Datenbankpfade.

Es wurden keine echten OpenAI-, Intervals.icu-, Garmin-, GitHub-, Wetter- oder Kalenderzugänge verwendet und keine Live-Athletendaten gelesen. Provider-Verhalten wurde anhand von Implementierung, Tests und einem leeren isolierten Lauf geprüft. Eine vollständige manuelle WCAG-Auditierung mit Screenreader, reale Netzwerkausfälle und Langzeitmessungen mit einer großen Produktionsdatenbank waren nicht Bestandteil dieser Prüfung.

### Validierungsergebnisse

| Prüfung | Ergebnis |
|---|---|
| Python-Syntax | bestanden |
| Docker-Build `ai-coach:review-54f60b7` | bestanden |
| Unit Tests im SQLCipher-Container | **187 ausgeführt**: 184 bestanden, 3 übersprungen, ca. 8:52 Minuten |
| Nativer Windows-Testlauf | 184 Setup-Fehler, weil der erforderliche SQLCipher-Treiber nicht verfügbar ist |
| Python-Abhängigkeiten (`pip-audit`) | keine bekannten Schwachstellen gefunden |
| Browser-Smoke-Test | alle Tabs erreichbar, keine Console-/Page-Errors, kein horizontaler Overflow |
| Base-Image-CVE-Scan | lokal nicht durchgeführt; Docker Scout verlangte eine Anmeldung |

Der native Testfehler ist kein Produktfehler: Die Anwendung verweigert ohne SQLCipher absichtlich den Start. Er zeigt aber, dass der in README und CI prominent genannte native Windows-Befehl nicht die kanonische lokale Validierung liefern kann.

## 3. UI/UX

### Positiv

- Die Anwendung wirkt visuell konsistent, ruhig und klar mobile-first. Die dunkle Farbgebung, Karten, Abstände und Statusfarben sind kohärent.
- Bei den geprüften mobilen und Desktop-Breiten trat in keinem Tab horizontaler Seiten-Overflow auf.
- Die feste Bottom-Navigation ist gut erreichbar und die sechs Hauptziele sind auf kleinen Displays verständlich beschriftet.
- Formulare besitzen überwiegend sichtbare Labels; Fokusmarkierungen, `aria-live`, reduzierte Bewegung und ausreichend große Hauptaktionen sind vorhanden.
- Die Settings-Gruppen sind einklappbar und reduzieren die anfängliche visuelle Last.
- Externe Daten werden häufig mit Status, Quelle oder Zeitstempel erklärt. Das stärkt Vertrauen.

### UI-01 – Versteckte Statusindikatoren sind permanent sichtbar

**Priorität: Mittel · Reproduziert im Browser**

Jeder als `hidden` markierte `.dirty-indicator` wird dennoch angezeigt. Dadurch steht unter Profil- und Einstellungsbereichen bereits direkt nach dem Laden „Ungespeichert“. Im Tab „Geplant“ erscheint außerdem eine leere rote Kapsel, weil `.remote-delete-notice` trotz `hidden` gerendert wird.

**Ursache und Evidenz**

- `public/index.html` verwendet `hidden` für die Indikatoren.
- `public/styles.css` setzt auf den Komponenten explizit `display: inline-block` beziehungsweise `display: grid`.
- Eine Autoren-CSS-Regel für `display` kann den Standardzustand des HTML-Attributs `hidden` überschreiben; siehe [MDN zum globalen `hidden`-Attribut](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/hidden).
- Der Fehler war auf den mobilen Screenshots in Profil, Einstellungen und Geplant sichtbar.

**Empfehlung**

Eine globale Regel wie `[hidden] { display: none !important; }` ergänzen und mindestens einen Browsertest schreiben, der Sichtbarkeit vor und nach einer Änderung prüft. Die global durchgesetzte Semantik verhindert denselben Fehler bei zukünftigen Komponenten.

### UI-02 – Coach-Hinweis wird vom festen Composer überdeckt

**Priorität: Mittel · Reproduziert im Browser**

Der medizinische Hinweis unter dem Chat liegt teilweise hinter dem festen Nachrichten-Composer. Gerade der Sicherheits-/Haftungshinweis ist deshalb schlechter lesbar. Die Bottom-Navigation hat einen Abstandspuffer, der Coach-Inhalt jedoch nicht ausreichend für Composer **und** Navigation.

**Empfehlung**

Dem Coach-Scrollbereich eine aus der tatsächlichen Composer-/Nav-Höhe berechnete Unterkante geben, idealerweise über gemeinsame CSS-Variablen und `env(safe-area-inset-bottom)`. Den Hinweis zusätzlich oberhalb oder innerhalb des scrollbaren Nachrichtenbereichs platzieren.

### UI-03 – Tages-Check-in wirkt wie ein ungestyltes Fremdelement

**Priorität: Niedrig**

Der Absende-Button des Tages-Check-ins fällt auf Mobilgeräten auf die Browser-Standarddarstellung zurück. Er ist optisch kleiner und schwächer als andere Primäraktionen. Die CSS-Regel legt nur seine Ausrichtung, nicht seine Schaltflächenoptik fest.

**Empfehlung**

Ein gemeinsames Button-System (`primary`, `secondary`, `danger`, `compact`) verwenden und den Check-in als Primäraktion mit mindestens 44 × 44 CSS-Pixeln darstellen.

### UI-04 – Sprach- und Eingabeinkonsistenzen mindern Verständlichkeit

**Priorität: Niedrig**

- Standardwerte wie „Cycling“ und „Supportive, direct, and evidence-aware“ erscheinen in der deutschen Oberfläche auf Englisch.
- Zeitzone, Wettkampfdistanz in Metern, Zeit in Sekunden und externe IDs sind rohe technische Eingaben.
- Check-in-Skalen erklären nicht überall eindeutig, ob hohe Werte gut oder schlecht sind.
- Der Hinweis auf parallele Radfahrten klingt so, als müsse zwingend eine Aktivität gelöscht werden; legitime Doppelaufzeichnungen sind möglich.

**Empfehlung**

Lokalisierte Anzeigen, Auswahlfelder für Zeitzone/Sport, formatierte Distanz- und Zeit-Editoren, beschriftete Skalenenden und eine neutrale „prüfen/ignorieren“-Option vorsehen. Intern können die bisherigen Normalformen erhalten bleiben.

## 4. Usability und Informationsarchitektur

### Aktuelle Zuordnung

| Tab | Aktueller Inhalt | Bewertung |
|---|---|---|
| Coach | Chat, Schnellprompts, adaptive Hinweise, Composer | Kerntask passend; Sicherheitsdisclaimer kollidiert visuell mit Composer |
| Aktivitäten | Historie, Filter/Suche, Feedback, Activity-Sync | Schlüssig und gut abgegrenzt |
| Geplant | Kalender, Wetter, adaptive Anpassungen, Wettkämpfe, Workout-Bibliothek, Mehrwochenpläne | Deutlich überladen; drei verschiedene Planungsebenen in einer langen Seite |
| Leistung | aktuelle Kennzahlen und Verläufe | Schlüssig; Quellenkennzeichnung ist wichtig und vorhanden |
| Profil | langfristiges Athletenprofil sowie täglicher Check-in und Verlauf | Vermischt seltene Stammdatenpflege mit täglicher Routine |
| Einstellungen | Integrationen, Sync-Zeitraum, Modell, Coach-Kontext, Logs, Privacy, Nutzung, Notifications, Backup/Restore, Diagnose, Logout | Zu technisch und zu umfangreich für einen einzigen Zielpunkt |

### UX-01 – „Geplant“ und „Einstellungen“ bündeln zu viele mentale Modelle

**Priorität: Mittel**

Im Tab „Geplant“ stehen Tages-/Wochenkalender, Workout-Vorlagen, Zielwettkämpfe und vollständige Trainingspläne untereinander. Diese Objekte haben unterschiedliche Lebenszyklen und Aktionen. In „Einstellungen“ liegen persönliche Coach-Konfiguration, externe Konten, Datenschutz und Betriebsdiagnose nebeneinander. Das erschwert Auffindbarkeit und erhöht das Risiko, eine Remote-Aktion mit einer lokalen Aktion zu verwechseln.

### Empfohlene mobile Navigation

Die Anzahl von sechs Bottom-Navigationseinträgen kann beibehalten werden; die Inhalte sollten neu zugeschnitten werden:

| Neuer Tab | Inhalt | Verschobene aktuelle Inhalte |
|---|---|---|
| **Coach** | Chat, Schnellprompts, laufende Antwort, adaptive Hinweise | im Wesentlichen unverändert |
| **Heute** | Tages-Check-in, Readiness, heutiges Training, relevantes Wetter, ausstehendes Feedback | Check-in aus Profil; Tagesausschnitt aus Geplant/Leistung |
| **Verlauf** | Aktivitäten, Suche/Filter, Aktivitätsfeedback | bisher Aktivitäten |
| **Plan** | Segmentiert in **Kalender**, **Bibliothek**, **Ziele & Pläne**; adaptive Vorschauen klar im Kalender | bisher Geplant und Wettkämpfe |
| **Leistung** | Performance, Trends, Quellen und Datenfrische | bisher Leistung |
| **Mehr** | Athletenprofil, Anbindungen, Coach & Modell, Daten & Datenschutz, Betrieb & Diagnose | bisher Profil-Stammdaten und Einstellungen |

Innerhalb von „Plan“ sollten Segmente oder Unterseiten statt einer einzigen langen Seite verwendet werden. „Mehr“ sollte eine kurze Menüliste öffnen und die technischen Bereiche auf getrennte Seiten führen. Dadurch bleibt die Bottom-Navigation auf täglichen Aufgaben ausgerichtet.

### UX-02 – URL und Browsernavigation bilden den Zustand nicht ab

**Priorität: Niedrig bis Mittel**

Tabwechsel verändern weder Hash noch History. Reload und Zurücknavigation führen deshalb immer wieder zum Coach. Bei langen Formularen oder Supportanweisungen lässt sich kein konkreter Bereich verlinken.

**Empfehlung**

Tabs mindestens über Hash-Routen abbilden (`#today`, `#plan/library`, `#more/privacy`), ohne dafür ein Framework einzuführen. Den letzten nicht-sensitiven Zielort optional lokal merken.

## 5. Accessibility

### A11Y-01 – Bottom-Navigation hat keine vollständige Tab- oder Navigationssemantik

**Priorität: Mittel**

Die Bottom-Navigation verwendet Buttons und `aria-current`, aber keine konsistente Beziehung zwischen Steuerung und Panel. Es fehlen unter anderem `tablist`/`tab`/`tabpanel`, `aria-controls`, `aria-selected`, roving `tabindex` und Tastatursteuerung per Pfeiltasten – oder alternativ echte Links mit eindeutigen Routen und Landmark-Navigation.

Die erwarteten Beziehungen und Tastaturmuster sind in den [WAI-ARIA Authoring Practices für Tabs](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/) beschrieben.

**Empfehlung**

Da die Einträge ganze Ansichten navigieren, sind echte Links mit Hash-Routen wahrscheinlich semantisch einfacher als ein ARIA-Tabwidget. Zusätzlich Playwright + axe für Login, alle Hauptansichten, Dialoge und Formularfehler einführen.

### A11Y-02 – Kleine Hilfstexte und Kontrast wurden nicht systematisch abgesichert

**Priorität: Niedrig**

Mehrere Hilfs- und Statuszeilen liegen bei etwa 0,62–0,69 rem und verwenden zurückhaltende Grautöne. Das kann auf kleinen Displays und bei hoher Umgebungshelligkeit problematisch sein. Ein automatisierter Kontrasttest oder dokumentiertes WCAG-Ziel fehlt.

**Empfehlung**

Mindestens WCAG 2.2 AA als Ziel festlegen, Textgrößen-Tokens vereinheitlichen und Kontrastprüfung in den Browser-Smoke-Test aufnehmen. Dynamische Schriftvergrößerung bis 200 % separat prüfen.

## 6. Generelle Architektur und Wartbarkeit

### Positiv

- Das lokale, Single-Athlete-Modell ist konsequent umgesetzt und für den Produktscope angemessen.
- SQLite bleibt für bestätigte Profile und Wettkämpfe autoritativ; OpenAI-Konversationen sind nicht die Datenbank.
- Datenquellen und abgeleitete/geschätzte Werte tragen Herkunftsinformationen.
- Mutierende Planungsabläufe besitzen vielerorts Vorschau, Fingerprint und Idempotenzschutz.
- Provider-Daten werden als nicht vertrauenswürdige Daten behandelt und kompakt in den Coach-Kontext projiziert.
- Die Anwendung bleibt eigenständig; es besteht kein sachlicher Grund für eine Multi-Tenant- oder Hosted-Service-Architektur.

### ARCH-01 – Backend und Frontend sind schwer wartbare Monolithen

**Priorität: Mittel**

`server.py` umfasst rund 9.157 Zeilen und enthält HTTP-Routing, Authentisierung, SQL-Schema, Repositories, Provider-Clients, Sync-Orchestrierung, Backups, OpenAI, Prompting und Businesslogik. `public/app.js` umfasst rund 3.529 Zeilen und trägt State, Rendering, Formulare, Tabs und API-Client gemeinsam.

Das erhöht die Änderungskopplung: Ein Sync-Fix berührt leicht HTTP- oder Persistenzcode; UI-Quelltexttests erkennen strukturelle Fehler, aber kaum tatsächliches Browserverhalten.

**Empfehlung**

Schrittweise und ohne Framework-Zwang trennen:

- Backend: `db`, `repositories`, `providers`, `sync`, `coach`, `backup`, `http_api`;
- Frontend: `api`, `state`, `views`, `components`, `forms`, `navigation`;
- gemeinsame DTO-/Validierungsfunktionen an einer Stelle halten;
- zuerst die kritischen Sync- und Mutationspfade isolieren, weil dort der höchste Nutzen liegt.

### ARCH-02 – Schemaentwicklung erfolgt ad hoc beim Start

**Priorität: Mittel**

Tabellenanlage, `ALTER TABLE`, Datenmigration und Schemaerwartungen sind in der großen Initialisierungsfunktion verteilt. Eine explizite Schema-/Migrationsversion und eine nachvollziehbare, transaktionale Migrationshistorie fehlen. Restore-Kompatibilität hängt damit an manuell synchron gehaltenen Tabellen-/Spaltenlisten.

**Empfehlung**

Eine kleine interne Migrationstabelle mit monotoner Version einführen. Jede Migration sollte separat, transaktional, idempotent getestet und vor Backup/Restore dokumentiert werden. Eine externe ORM ist dafür nicht nötig.

### ARCH-03 – Deklarierte Foreign Keys werden nicht eingeschaltet

**Priorität: Mittel**

Das Schema enthält beispielsweise einen Fremdschlüssel von Kalenderkandidaten auf Kalenderquellen. Beim Öffnen einer Verbindung wird aber kein `PRAGMA foreign_keys = ON` gesetzt. SQLite deaktiviert Foreign-Key-Prüfungen standardmäßig pro Verbindung; siehe [offizielle SQLite-Dokumentation](https://www.sqlite.org/foreignkeys.html).

**Wirkung**

Verwaiste Datensätze und inkonsistente Löschreihenfolgen bleiben möglich, obwohl das Schema Integrität suggeriert.

**Empfehlung**

`PRAGMA foreign_keys = ON` unmittelbar nach jeder Verbindung aktivieren, mit `PRAGMA foreign_key_check` gegen Test-/Migrationsdaten prüfen und Löschpfade explizit mit `ON DELETE`-Verhalten versehen.

## 7. Ladezeiten, State und Synchronisationsmechanismen

### Messwerte des isolierten leeren Systems

| Request | Größe | beobachtete Dauer |
|---|---:|---:|
| erster authentisierter `/api/state/local` | 4,6 KB | ca. 813 ms |
| `/api/state` | 5,6 KB | ca. 1.471 ms |
| wiederholter lokaler State | 5,6 KB | ca. 705–801 ms |
| `app.js` | 165,5 KB | ca. 183 ms, unkomprimiert |
| `styles.css` | 52,4 KB | ca. 50 ms, unkomprimiert |
| `index.html` | 30,9 KB | ca. 59 ms, unkomprimiert |

Die Zahlen sind keine allgemeingültigen Benchmarks, zeigen aber, dass bereits ein leerer lokaler State relativ teuer ist. Mit realer Historie, SQLCipher-I/O und Wetter-/Release-Status steigt das Risiko deutlich.

### SYNC-01 – Normale Synchronisation schreibt die Workout-Bibliothek remote

**Priorität: Kritisch**

`sync_intervals()` ruft nach dem Snapshot-Abruf immer `sync_workout_library()` auf. Diese Funktion erstellt oder aktualisiert lokale Bibliothekseinträge bei Intervals.icu. Damit kann nicht nur der explizite Bibliotheks-Sync, sondern auch Folgendes remote schreiben:

- der normale Button „Synchronisieren“ im Aktivitäten-Tab;
- der Start-Sync;
- der tägliche automatische Sync;
- ein Vollabgleich;
- ein vom Chat ausgelöster Fresh-Data-Sync.

Das widerspricht der dokumentierten Grenze „Coach-Workouts bleiben lokal, bis die Person die Bibliothek ausdrücklich synchronisiert“.

**Evidenz**

- `server.py:6510–6526`: Intervals-Snapshot und anschließender Bibliotheks-Sync;
- `server.py:5820–5855`: Remote-Erstellung/-Aktualisierung lokaler Einträge;
- `server.py:9067–9104` und `server.py:9139`: Start-/Tagessync;
- `server.py:7815–7819`: Fresh-Data-Pfad im Coach-Chat.

**Empfehlung**

Provider-Lesesync und Remote-Schreibsync strikt trennen. `sync_intervals()` darf ausschließlich lesen. Bibliotheks-Uploads benötigen einen dedizierten API-Aufruf mit UI-Bestätigung und einer serverseitig geprüften Liste/Fingerprint der betroffenen Einträge. Tests müssen beweisen, dass Startup, Daily, Activity und Coach-Freshness niemals Bibliothek oder Kalender schreiben.

### SYNC-02 – Start- und Tagessync übertragen ausstehende Wettkampfänderungen

**Priorität: Hoch**

`safe_sync()` führt `sync_competitions()` mit standardmäßig aktiviertem `push_local` aus. `safe_sync()` läuft beim Start und täglich im Hintergrund. Ein lokal gespeicherter oder zur Löschung vorgemerkter, verknüpfter Wettkampf kann daher später ohne Klick auf den separaten Wettkampf-Sync zu Intervals.icu übertragen werden.

**Empfehlung**

Automatische Synchronisationen nur lesend ausführen (`push_local=False`). Remote-Push und Remote-Delete ausschließlich über eine ausdrückliche Wettkampf-Sync-Aktion erlauben. Die UI sollte vorher „erstellt / geändert / gelöscht“ mit Zielsystem und Anzahl anzeigen.

### SYNC-03 – Tageserkennung mischt lokale und UTC-Datumswerte

**Priorität: Mittel bis Hoch**

Die tägliche Schleife bildet `today` in lokaler Zeit, vergleicht es aber mit den ersten zehn Zeichen von Zeitstempeln, die in UTC gespeichert werden. Rund um Mitternacht kann ein Job in Zeitzonen östlich von UTC mehrfach alle fünf Minuten laufen; westlich von UTC kann er verzögert oder übersprungen werden.

**Empfehlung**

Entweder ein explizites `last_*_local_date` in der konfigurierten Athletenzeitzone speichern oder den UTC-Zeitpunkt korrekt parsen und vor dem Datumsvergleich umrechnen. DST-Grenzen und 23:30–00:30 Uhr sollten Tests erhalten.

### PERF-01 – Gesamthistorie und vollständiger Browser-State wachsen unbeschränkt

**Priorität: Hoch**

Bei „gesamte Historie“ wird die sonstige Begrenzung auf 500 Aktivitäten nicht angewendet. `/api/state` liefert anschließend große Sammlungen gemeinsam aus, darunter Aktivitäten, geplante Einträge, Planungssicht, Bibliothek, Check-ins und Feedback. Einige Inhalte werden in mehreren Darstellungen dupliziert. Der Browser lädt und rendert diesen Gesamtzustand wiederholt.

**Wirkung**

- linear wachsende JSON-, Parse-, Speicher- und Renderkosten;
- hohe Latenz auf Mobilgeräten;
- größere SQLCipher-Lock-Zeiten;
- mögliche Browserabstürze bei mehrjähriger Historie;
- unnötige Übertragung bei Status-Polling.

**Empfehlung**

State in fachliche Endpunkte teilen und paginieren: `/activities`, `/plan`, `/library`, `/performance`, `/profile`, `/sync/status`. Aktivitäten cursorbasiert laden, Planbereiche nur beim Öffnen abrufen und Listen virtualisieren. „Gesamte Historie“ darf den serverseitigen Snapshot vollständig halten, aber nicht ungefiltert in jede UI-Antwort gelangen.

### PERF-02 – Polling ist weder Single-Flight noch differenziell

**Priorität: Mittel**

Während eines Syncs ruft das Frontend etwa alle 1,5 Sekunden den vollständigen State ab, ansonsten sichtbar jede Minute. Es existiert kein allgemeiner In-Flight-Schutz und kein `AbortController` für diese Loads. Eine Sequenznummer verhindert lediglich, dass ältere Antworten gerendert werden; die Serverarbeit läuft weiter. Mehrere Tabs können sich der Rate-Limit-Grenze von 180 Requests pro Minute und IP nähern.

**Empfehlung**

Einen kleinen `/api/sync/status`-Endpunkt mit Versionsnummer bereitstellen, nur eine laufende Abfrage erlauben und alte Requests abbrechen. Den vollständigen Bereich erst bei geänderter Version nachladen. Mittelfristig reichen Server-Sent Events für Statusänderungen; permanentes WebSocket-Design ist nicht erforderlich.

### PERF-03 – Jede Session-Prüfung schreibt und serialisiert DB-Zugriffe

**Priorität: Mittel**

Bei fast jedem authentisierten API-Aufruf wird die Sessionablaufzeit in SQLCipher aktualisiert. Gleichzeitig serialisiert ein globaler DB-Lock wesentliche Zugriffe. Polling erzeugt dadurch auch für reine GETs Schreib-I/O, WAL-Aktivität und Konkurrenz mit Sync-Jobs. Der Browser-Cookie-Max-Age wird bei dieser serverseitigen Verlängerung nicht aktualisiert, sodass die tatsächliche Browser- und DB-Lebensdauer unterschiedlich modelliert ist.

**Empfehlung**

`last_seen`/Expiry nur gedrosselt aktualisieren, etwa alle 5–15 Minuten. Auth-Prüfungen ansonsten lesend halten, Sessionsemantik dokumentieren und DB-Zugriff schrittweise über klar begrenzte Repository-Transaktionen führen.

### PERF-04 – Statische Assets nutzen Versionierung, aber keine effiziente Auslieferung

**Priorität: Niedrig bis Mittel**

Die Hauptassets tragen Versionsparameter, werden jedoch mit `no-cache`, ohne ETag/Last-Modified und im Service Worker network-first geladen. Im Test wurden sie unkomprimiert ausgeliefert. Dadurch wird die vorhandene Versionierung nicht für langes Immutable-Caching genutzt.

**Empfehlung**

Versionierte Assets cache-first und `Cache-Control: public, max-age=31536000, immutable` ausliefern; HTML und Service Worker weiter revalidieren. Gzip/Brotli am vertrauenswürdigen HTTPS-Reverse-Proxy aktivieren.

## 8. Externe Anbindungen

### Intervals.icu

**Stärken**

- Providerdaten werden begrenzt, dedupliziert und mit Fingerprints/Quellen verarbeitet.
- Remote-Kalenderlöschungen sind auf app-eigene, zukünftige Workouts beschränkt.
- Fehlerstatus und letzter guter Snapshot bleiben erhalten.

**Risiko**

Die Trennung von Lesesync, Bibliotheks-Push, Plan-Kalender-Push und Wettkampf-Push ist in der Orchestrierung nicht konsequent. SYNC-01 und SYNC-02 sind deshalb die wichtigsten Integrationsbefunde.

### Garmin Connect

**Stärken**

- optional, serverseitige Tokens, Fixture-Pfad für Entwicklung, begrenzte Verarbeitung;
- Garmin- und Intervals-Daten behalten Herkunftsinformationen.

**Risiken und Empfehlungen**

- Die Integration hängt von einem Drittanbieter-SDK und einer nicht als stabile öffentliche API behandelten Provideroberfläche ab. Providerdrift, MFA- und Rate-Limit-Fehler sollten als erwartbarer Betriebszustand sichtbar sein.
- UI- und Konfigurationstexte sollten klarer unterscheiden, wann ein bestehender Tokenstore genügt und keine Passwortangabe erforderlich ist.
- Exponentiellen Backoff, letzten erfolgreichen Teilbereich und „erneut anmelden erforderlich“ getrennt anzeigen.

### Öffentliche iCalendar-Quellen

**Stärken**

Die Implementierung ist für serverseitige URL-Abrufe sorgfältig gehärtet: nur HTTPS/Port 443, öffentliche Ziel-IP, DNS-/IP-Prüfung, kein Redirect, TLS-Mindestversion, Größenlimits und Last-Good-Verhalten.

### EXT-01 – Wiederkehrende Kalenderereignisse werden vollständig abgelehnt

**Priorität: Mittel / Feature-Gap**

Jede Quelle mit `RRULE` wird abgewiesen. Dadurch fehlen typische regelmäßig wiederkehrende Arbeitszeiten, Vereinsfahrten oder Termine – gerade Daten, die für Trainingsplanung besonders relevant sind.

**Empfehlung**

Eine bewusst begrenzte RFC-5545-Untermenge unterstützen: tägliche/wöchentliche Wiederholung mit `COUNT` oder `UNTIL`, harte Expansionsgrenze und nur innerhalb des Sync-Fensters. Komplexe Regeln weiter mit klarer Fehlermeldung ablehnen.

### Wetter / Open-Meteo

**Stärken**

Caching, Backoff, Quellenhinweis und begrenzte Vorhersagen sind vorhanden.

### EXT-02 – Verfügbarkeit ist nicht strukturiert konfigurierbar

**Priorität: Mittel / Feature-Gap**

Trainingsfenster und Arbeitszeiten sind teilweise als Annahmen in Code/Prompt hinterlegt oder müssen im Freitextprofil stehen. Wetter kann dadurch technisch präzise sein, aber gegen falsche zeitliche Annahmen geplant werden.

**Empfehlung**

Eine kleine strukturierte Wochenverfügbarkeit mit früh/spät, maximaler Dauer und Indoor-Option einführen. Sie bleibt lokale, explizit bestätigte Profildaten und wird kompakt in den Coach-Kontext projiziert.

### GitHub Release Check

Der Release-Check ist funktional sinnvoll, sollte aber nicht die Kern-State-Latenz beeinflussen. Cache und Fehlerisolierung beibehalten; den Status nur im Diagnose-/Updatebereich laden.

## 9. Security, Privacy und Vertrauen

### Positiv

- `APP_PASSWORD` schützt UI/API und dient als SQLCipher-Schlüssel; unsicherer Start wird verweigert.
- Cookies sind HttpOnly/SameSite, schreibende Requests CSRF-geschützt und Login/API rate-limitiert.
- Credentials bleiben serverseitig; CSP, Frame-Schutz, MIME-Nosniff und sichere Markdown-Behandlung sind vorhanden.
- Voice-Audio wird nicht persistiert.
- Request-/Provider-Logs enthalten überwiegend Metadaten statt Nutzdaten.
- Container läuft als Nicht-Root; die dokumentierte Runtime ist read-only und nutzt `no-new-privileges`.
- Der Dependency-Audit meldete für die gepinnten Python-Abhängigkeiten keine bekannten Schwachstellen.

### COACH-01 – Schlüsselworterkennung autorisiert mutierende Coach-Aktionen trotz Negation

**Priorität: Kritisch · Direkt reproduziert**

Der Server klassifiziert den Nutzertext per regulären Ausdrücken und erzwingt bei Treffern ein mutierendes Tool. Die Erkennung versteht Negation, Fragen und rein erklärende Wünsche nicht zuverlässig.

Reproduzierte Beispiele:

| Eingabe | erkannte/erzwungene Aktion |
|---|---|
| „Plane **keine** Trainingseinheit, sondern erkläre nur die Optionen.“ | Workout speichern |
| „Lösche den Wettkampf **nicht**.“ | Wettkampf löschen |
| „Synchronisiere den Wettkampf **nicht** mit Intervals.icu.“ | Wettkampf synchronisieren |
| „Wende den adaptiven Vorschlag **nicht** an.“ | Adaptive Änderung anwenden |
| „Bitte **keinen** neuen Wettkampf anlegen.“ | Wettkampf speichern |
| „Was macht Training mit meiner Form?“ | Workout-Erstellung erkannt |

Selbst wenn nachgelagerte Validierung einzelne Fehlaktionen verhindert, ist Rohtext-Keyword-Matching keine belastbare Einwilligung zu einer dauerhaften oder entfernten Mutation.

**Empfehlung**

Mutationen zweistufig machen:

1. Der Coach darf aus normalem Chat nur eine strukturierte **Vorschau** zurückgeben.
2. Die UI zeigt genaue Objekte, Zielsystem, Änderungen und Löschungen.
3. Erst eine separate Bestätigung erzeugt serverseitig ein kurzlebiges, einmaliges Action-Token, gebunden an Nutzer-Session, Operation und Payload-Hash.
4. Nur der bestätigte API-Aufruf darf das Mutationstool ausführen.

Read-only-Tools können weiterhin direkt im Chat laufen. Negationserkennung darf die UX verbessern, aber nie die Sicherheitsgrenze bilden.

### SEC-01 – Redaction-Liste lässt sensible Konfigurationswerte aus

**Priorität: Hoch**

Die zentrale Textredaktion berücksichtigt unter anderem API-Key, Garmin-Passwort, GitHub-Token und App-Passwort, aber nicht Garmin-E-Mail und `CALENDAR_ICAL_URL`. Private Kalender-URLs enthalten häufig nicht erratbare Pfade oder Tokens und sind praktisch Credentials. Exceptiontexte oder Tracebacks könnten sie daher in Logs übernehmen.

**Empfehlung**

- alle exakten geheimen/identifizierenden Konfigurationswerte zentral registrieren, einschließlich Garmin-E-Mail und Kalender-URL;
- URL-Userinfo, bekannte Token-Queryparameter und lange Secret-Pfade strukturell entfernen;
- Redaction-Tests für Exceptions, verschachtelte Fehler, URLs und Teilstrings ergänzen;
- Providerfehler bevorzugt in definierte Fehlercodes statt rohe Exceptiontexte überführen.

### DATA-01 – Löschdialog unterschätzt den tatsächlichen Umfang

**Priorität: Hoch**

Der Bestätigungsdialog nennt lokale Chats, Snapshots, Entwürfe und Profile. Serverseitig werden zusätzlich unter anderem Workout-Bibliothek, Wettkämpfe, Trainingspläne, Check-ins, Aktivitätsfeedback, adaptive Anpassungen, Kalenderquellen/-kandidaten, externe Kalenderereignisse, Sessions, Einstellungen und Syncstatus gelöscht.

**Wirkung**

Eine Person kann weit mehr dauerhafte Daten verlieren als unmittelbar vor der irreversiblen Aktion angekündigt.

**Empfehlung**

Vollständige Kategorien und Remote-Ausnahmen anzeigen, vorher verschlüsseltes Backup/Export anbieten und eine stärkere Bestätigung verwenden, etwa Eingabe von `LOKAL LÖSCHEN`. Nach Abschluss klar sagen, ob entfernte OpenAI-/Providerdaten gelöscht wurden oder nicht.

### SEC-02 – `http.server` ist nur innerhalb der dokumentierten Vertrauensgrenze vertretbar

**Priorität: Mittel / akzeptiertes Restrisiko**

Python dokumentiert `http.server` ausdrücklich als nicht für Produktion empfohlen und nur mit grundlegenden Sicherheitsprüfungen versehen; siehe [Python-Dokumentation](https://docs.python.org/3.12/library/http.server.html). Für die definierte private LAN/VPN-Nutzung hinter einem vertrauenswürdigen HTTPS-Reverse-Proxy ist das ein bewusst akzeptierbarer Trade-off. Eine direkte öffentliche Exposition wäre dagegen nicht vertretbar.

**Empfehlung**

Die Grenze in UI/README/Container-Vorlage sichtbar halten. Falls künftig öffentliche Erreichbarkeit, höhere Parallelität oder integriertes TLS gefordert wird, zuerst auf einen gewarteten WSGI/ASGI-Server und ein klar getrenntes App-Interface wechseln – nicht die jetzige Runtime stillschweigend öffentlich stellen.

### PRIV-01 – Coach-Datenweitergabe ist technisch einsehbar, aber im Arbeitsfluss zu wenig sichtbar

**Priorität: Mittel**

Gesundheitshinweise, Check-ins, Wettkampfdaten, Aktivitätsfeedback und Namen externer Kalendertermine können Bestandteil des OpenAI-Kontexts sein. Die Kontextvorschau existiert, ist jedoch tief in den Einstellungen verborgen. Direkt an den Eingabefeldern ist nicht immer ersichtlich, dass Inhalte an OpenAI gesendet werden können.

**Empfehlung**

Bei sensiblen Feldern eine kurze Kennzeichnung „wird für Coach-Anfragen an OpenAI übermittelt“ anbieten, mit Link zur aktuellen Kontextvorschau. Optional pro Kategorie eine lokale Ein-/Ausschlusskontrolle, ohne Rohsnapshots oder Persistenz zu verändern.

## 10. Datenintegrität, Backup und Recovery

### REC-01 – Restore sperrt nicht den gesamten Anwendungsbetrieb

**Priorität: Mittel bis Hoch**

Der Restore validiert die hochgeladene Datenbank und hält den DB-Lock während Checkpoint und Dateiaustausch. Gleichzeitig kann ein Provider-Sync vor dem Lock externe Daten abrufen und nach dem Restore seine alten Ergebnisse in die wiederhergestellte DB schreiben. Der Dateiaustausch ist geschützt, nicht aber der vollständige Maintenance-Zeitraum.

**Empfehlung**

Einen globalen Maintenance-Gate einführen: neue Chats/Syncs ablehnen, laufende Jobs auslaufen lassen oder abbrechen, Restore durchführen, Verbindungen/Cache neu initialisieren und erst danach wieder freigeben. Diesen Race mit einem blockierten Provider-Test reproduzieren.

### REC-02 – Backup und Privacy-Export werden vollständig im Speicher aufgebaut

**Priorität: Mittel**

Der Datenbankdownload liest die komplette DB in ein Byteobjekt. Der Privacy-Export lädt zahlreiche Tabellen/Snapshots in ein großes Dict und serialisiert anschließend alles. Bei langen Historien kann dies den Container speicherseitig belasten oder durch OOM beenden.

**Empfehlung**

Dateidownload streamen, Export als inkrementelles ZIP/JSONL erzeugen und ein dokumentiertes Größen-/Zeitlimit mit verständlicher Fehlermeldung setzen. Ein Backup sollte vor dem Download weiter über SQLite/SQLCipher-konsistente Mechanismen erzeugt werden.

### REC-03 – Bereinigung langlebiger Hilfstabellen ist unvollständig

**Priorität: Niedrig**

Abgelaufene Sessions werden vor allem beim erneuten Vorlegen bereinigt. Auch der In-Memory-Rate-Limit-Index kann über sehr viele Quell-IPs wachsen. Im privaten Single-User-Betrieb ist das geringe Dringlichkeit, sollte aber durch periodische, begrenzte Bereinigung geschlossen werden.

## 11. Zugriff des Coaches auf Funktionen

### Aktuelle Fähigkeitsmatrix

| Bereich | Coach kann lesen | Coach kann lokal ändern | Coach kann remote ändern |
|---|---|---|---|
| Aktivitäten/Leistung | aktuelle Snapshots, Performance, Feedback | Aktivitätsfeedback speichern | Fresh-Data-Sync auslösen; Providerdaten selbst nicht verändern |
| Workout-Bibliothek | lokale Einträge und Status | Einträge/Planinhalte speichern | Vorlagen zu Intervals.icu erstellen/aktualisieren |
| Trainingsplanung | geplante Einträge, Wetter, Kalender | Bibliotheksplan und adaptive Anpassung anwenden | bei explizitem Sync Kalenderworkouts schreiben |
| Wettkämpfe | lokale und verknüpfte Wettkämpfe | speichern/löschen | verknüpfte Events erstellen/ändern/löschen |
| Check-in | jüngste lokale Check-ins | im normalen Chat nicht direkt; Morning-Check-in läuft mutierungsfrei | keine |
| Externe Kalender | Verfügbarkeit/Termine im Kontext | Quellen nur über UI/API | keine Kalenderschreibrechte |

### Positiv

- Der Morning-Check-in ruft den Coach ohne Mutationsrechte auf.
- Adaptive Neuplanung besitzt Vorschau, Freigabe und Fingerprint.
- Remote-Kalenderlöschungen sind auf app-eigene zukünftige Workouts eingeschränkt.
- Externe Texte werden nicht als Instruktionen behandelt.
- Tool-Ergebnisse und Idempotenzmechanismen reduzieren Doppelaktionen.

### COACH-02 – Geplante Workouts werden umfangreich und doppelt in den Coach-Kontext geschrieben

**Priorität: Hoch**

Der strukturierte Athletenkontext enthält bis zu 250 lokale geplante Workouts mit umfangreichen Payloads und Beschreibungen. Beim Aufbau des finalen Trainingskontexts wird dieser gesamte strukturierte Kontext serialisiert; anschließend wird `local_planned_workouts` nochmals separat serialisiert. Damit erreichen dieselben Planinformationen den Prompt doppelt und ohne eine auf den Coachingzweck zugeschnittene enge Projektion.

**Evidenz**

- `server.py:7167`: vollständige lokale geplante Workouts im strukturierten Kontext;
- `server.py:7226–7232`: Serialisierung des Gesamtkontexts und erneute Serialisierung der geplanten Workouts.

**Wirkung**

- unnötige Input-Tokens und Kosten;
- längere Coach-Latenz;
- wichtige aktuelle Performance- oder Feedbackdaten können aus dem Modellkontext verdrängt werden;
- große Freitextbeschreibungen erhöhen die Menge externer Daten, die an OpenAI übertragen wird.

**Empfehlung**

Nur eine kompakte Projektion einmalig übergeben: relevanter Zeitraum, Datum, Sport, Dauer, Ziel/Intensität, Status und stabile lokale ID. Lange Beschreibungen und vollständige Providerpayloads weglassen; vergangene oder weit entfernte Planungen aggregieren. Ein Token-/Größenbudget pro Kontextsektion und Tests für Maximalgrößen ergänzen.

### COACH-03 – Mutierende Tools sind im normalen Chat zu breit exponiert

**Priorität: Hoch als Teil von COACH-01**

Die Toolliste enthält im normalen Coach-Dialog neben Leseoperationen auch speichernde, löschende und synchronisierende Funktionen. Der Server besitzt zwar zusätzliche Prüfungen, aber die Angriffs- und Fehlbedienungsfläche bleibt unnötig groß. In Kombination mit der Keyword-Klassifizierung wird daraus ein konkretes Zustimmungsproblem.

**Empfohlenes Berechtigungsmodell**

- **Standardchat:** ausschließlich Lesen, Berechnen und Vorschlagen.
- **Expliziter UI-Modus „Änderung vorbereiten“:** strukturierte Vorschau erzeugen, noch ohne Mutation.
- **Bestätigungsdialog:** genaue lokale/remote Wirkung, Diff und Zielsystem.
- **Einmal-Token:** nur die freigegebene Operation und Payload.
- **Audit-Eintrag:** Zeitpunkt, Aktion, Ziel, Ergebnis und auslösende Bestätigung – ohne sensiblen Prompttext.
- **Remote-Sync:** stets eigener Freigabeschritt; niemals Nebenwirkung eines Read-/Freshness-Syncs.

### COACH-04 – Antwortsteuerung ist keine echte Unterbrechung

**Priorität: Niedrig bis Mittel / Feature-Gap**

„Steuern“ stellt eine Folgeanweisung bereit, beendet aber die laufende OpenAI-Anfrage nicht. Es gibt weder Streaming noch sichtbare Teilantwort noch echte Cancel-Funktion. Bei hoher Latenz wirkt die App dadurch blockiert und kann bereits verbrauchte Tokens nicht begrenzen.

**Empfehlung**

Responses streamen, Server-Cancel unterstützen und UI-seitig zwischen „Abbrechen“ und „danach weiterfragen“ unterscheiden. Mutationen dürfen erst nach vollständig validierter Toolausgabe und separater Bestätigung stattfinden.

## 12. PWA- und Offline-Verhalten

### PWA-01 – Offline ist nur die App-Hülle, nicht die Anwendung nutzbar

**Priorität: Mittel / Feature-Gap**

Der Service Worker cached statische Shell-Assets, aber keine authentisierten State-Daten. Offline öffnet sich gegebenenfalls die Oberfläche, Aktivitäten, Plan und Check-ins sind jedoch nicht sinnvoll nutzbar. Es gibt keine Queue für lokale Entwürfe oder Feedback.

**Empfehlung**

Den Zustand transparent als „offline/read-only“ anzeigen und einen bewusst kleinen verschlüsselungsarmen Browsercache vermeiden, solange kein klares Threat Model besteht. Als risikoarme erste Stufe nur nicht-sensible Entwürfe in-memory halten und nach Reconnect aktiv bestätigen lassen. Wenn echter Offlinezugriff gewünscht ist, braucht er eine eigene Datenschutzentscheidung, nicht bloß mehr Service-Worker-Caching.

### PWA-02 – Benachrichtigungen sind keine verlässlichen Hintergrund-Pushs

**Priorität: Niedrig / Feature-Gap**

Die aktuelle Notification-Funktion kann lokale Browserhinweise erzeugen, ist aber kein serverseitiger Background-Push. Geschlossene oder vom Betriebssystem suspendierte PWAs erhalten keine verlässlichen Trainings-/Check-in-Erinnerungen.

**Empfehlung**

Die UI-Texte entsprechend präzisieren. Echten Web Push nur einführen, wenn Schlüsselverwaltung, HTTPS-Proxy, Opt-in, Widerruf und keine sensiblen Notification-Inhalte sauber gelöst sind.

## 13. Feature-Gaps

Nach Nutzen und Scope geordnet:

### Hoher Nutzen

1. **Heute-Ansicht:** Readiness, Check-in, heutiges Workout, Wetter, offene Rückmeldung und relevante Planänderung an einem Ort.
2. **Sichere Änderungsfreigabe:** strukturierte Coach-Vorschau mit Diff, Zielsystem und einmaliger Bestätigung.
3. **Paginierte Historie:** cursorbasierte Aktivitäten und Chat-Historie statt Gesamt-State.
4. **Konfigurierbare Wochenverfügbarkeit:** strukturierte Zeitfenster und Indoor-/Outdoor-Präferenzen.
5. **Streaming und echtes Abbrechen:** schnellere gefühlte Antwort und bessere Kostenkontrolle.

### Mittlerer Nutzen

6. **Wiederkehrende iCalendar-Termine** in einer begrenzten sicheren Untermenge.
7. **Änderungshistorie/Undo** für Profil, Bibliothek, Wettkämpfe und lokale Planänderungen.
8. **Chat-Suche/Paginierung:** derzeit ist nur ein begrenzter letzter Ausschnitt komfortabel sichtbar.
9. **Bulk-Aktionen in Bibliothek und Plan:** mehrere Einträge markieren, verschieben oder bewusst synchronisieren.
10. **Datenfrische-Timeline:** pro Provider letzter Versuch, letzter Erfolg, Teilstatus und nächste Wiederholung.

### Nur bei explizitem Bedarf

11. Echter Offline-Datenzugriff mit eigenem Datenschutz-/Verschlüsselungskonzept.
12. Echter Web Push.
13. Drag-and-drop im Kalender; auf Mobilgeräten sind explizite Verschiebeaktionen oft zuverlässiger.

Nicht empfohlen sind ein Multi-Athlete-Umbau, eine öffentliche Direktbereitstellung oder die Ablösung durch einen gehosteten Agent-/Webhook-Flow; diese würden den absichtlich privaten Produktscope verletzen.

## 14. Tests und Qualitätsabsicherung

### Positiv

- Die 187 Standardbibliothek-Tests decken viele Auth-, CSRF-, SQLCipher-, Provider-, Prompt-, Backup- und Mutationsgrenzen ab.
- Externe Dienste werden gemockt; Testdatenbanken sind temporär.
- Container- und CI-Versionen sind gepinnt, der Base-Image-Digest ist fixiert.
- Der vollständige SQLCipher-Lauf war erfolgreich.

### TEST-01 – Es fehlen echte Browser-, Accessibility- und visuelle Regressionstests

**Priorität: Mittel bis Hoch**

Frontendtests prüfen überwiegend Quelltextfragmente. Dadurch blieben die permanent sichtbaren `hidden`-Indikatoren, der ungestylte Check-in-Button und die Composer-Überdeckung unentdeckt. Es gibt keinen automatisierten Login-/Tab-/Dialog-Smoke-Test und keinen Accessibility-Scan.

**Empfehlung**

Einen kleinen Playwright-Satz gegen den Docker-Fixture-Start in CI ergänzen:

- Login und CSRF;
- alle Navigationseinträge bei Mobile/Desktop;
- `hidden`-Zustände vor/nach Änderung;
- Workout-/Wettkampf-/Delete-Vorschauen ohne echte Provider;
- kein horizontaler Overflow;
- axe-Prüfung kritischer Views;
- Screenshot nur für wenige stabile Kernansichten.

### TEST-02 – Lokaler Testbefehl und tatsächliche Windows-Laufzeit passen nicht zusammen

**Priorität: Mittel**

Der native Windows-Lauf meldete 184 Setup-Fehler, weil das erforderliche SQLCipher-Paket dort nicht verfügbar ist. Die Projektanweisungen erklären zwar Docker als kanonische Windows-Runtime, README und Standard-Validierung stellen den nativen Befehl aber weiterhin prominent dar.

**Empfehlung**

Einen kanonischen Docker-Testbefehl oder ein Skript `scripts/test.ps1` dokumentieren, das Repository read-only mountet und den SQLCipher-Container nutzt. Native Syntaxprüfung kann separat bleiben.

### TEST-03 – Testsuite ist langsam und erzeugt ResourceWarnings

**Priorität: Niedrig bis Mittel**

Der vollständige Lauf dauerte im lokalen Container fast neun Minuten. SQLCipher-Initialisierung pro Test ist ein wahrscheinlicher Kostentreiber. Einzelne HTTPError-Mocks erzeugten `ResourceWarning`-Meldungen.

**Empfehlung**

Eine bereits migrierte leere Testdatenbank pro Klasse sicher kopieren, teure Integrationspfade markieren/parallelisieren und Response-Mocks korrekt schließen. Zusätzlich Coverage, Formatter/Linter und eine leichte statische Typprüfung schrittweise einführen.

### TEST-04 – Supply-Chain-Prüfung ist unvollständig

**Priorität: Niedrig bis Mittel**

Python-Pakete waren im Audit unauffällig. Ein reproduzierter OS-/Base-Image-CVE-Scan, SBOM-Artefakt und Signaturnachweis waren in der lokalen Prüfung beziehungsweise den betrachteten Workflows nicht vollständig sichtbar.

**Empfehlung**

Im Publish-Workflow SBOM erzeugen, Image nach Build scannen und signieren; Schwellenwerte für kritische/hohe CVEs mit dokumentierter Ausnahmebehandlung festlegen.

## 15. Betrieb, Deployment und Observability

### Positiv

- Container läuft als Nicht-Root und ist für read-only Root-Filesystem sowie persistenten `/data`-Mount ausgelegt.
- Strukturiertes JSONL-Logging rotiert und vermeidet bewusst Payload-/Athleteninhalte.
- Diagnose- und Logansicht erleichtern privaten Betrieb ohne externe Telemetrie.
- Backup-, Restore- und SQLCipher-Prüfungen respektieren durable Athletendaten.

### OPS-01 – Healthcheck prüft keine Betriebsbereitschaft

**Priorität: Mittel**

Der Health-Endpunkt bestätigt im Wesentlichen, dass der HTTP-Prozess antwortet. Eine nicht öffnungsfähige Datenbank, ein nicht schreibbares `/data`, erschöpfter Speicherplatz oder ein festgefahrener Maintenance-Zustand können unentdeckt bleiben.

**Empfehlung**

Liveness und Readiness trennen. Readiness sollte eine harmlose SQLCipher-Leseoperation, Schema-Version, Schreibbarkeit des Datenverzeichnisses und Maintenance-Status prüfen – ohne Secrets oder Athletendaten zurückzugeben.

### OBS-01 – Provider- und HTTP-Abläufe sind nicht durchgängig korrelierbar

**Priorität: Niedrig bis Mittel**

HTTP-Logs haben Request-IDs, asynchrone Provider-/Sync-Logs lassen sich aber nicht immer auf die auslösende manuelle Aktion, den Chat oder den Hintergrundjob zurückführen. Bei überlappenden Jobs erschwert das Ursachenanalyse.

**Empfehlung**

Eine `operation_id` durch Sync-Orchestrierung, Provider-Calls und Abschlussstatus führen. Nur technische Metadaten loggen: Auslöserklasse, Provider, Phase, Dauer, Anzahl und Fehlercode – keine URLs mit Tokens, Inhalte oder Credentials.

### OPS-02 – Container-Härtung kann noch enger werden

**Priorität: Niedrig**

Nicht-Root, read-only und `no-new-privileges` sind eine gute Basis. Ergänzend sind `--cap-drop=ALL`, CPU-/Memory-/PID-Limits und ein rootless Docker-Host sinnvoll, soweit Garmin-/SQLCipher-Betrieb nicht beeinträchtigt wird. Docker beschreibt Capability-Reduktion und Rootless-Betrieb in der [offiziellen Engine-Sicherheitsdokumentation](https://docs.docker.com/engine/security/).

## 16. Priorisierte Maßnahmen-Roadmap

### Phase 0 – Vor weiteren Funktionsänderungen

1. COACH-01/COACH-03: mutierende Tools aus dem normalen Chat entfernen und Bestätigungs-Token einführen.
2. SYNC-01: Intervals-Lesesync vollständig vom Bibliotheks-Push trennen.
3. SYNC-02: automatische Wettkampfsynchronisation strikt read-only machen.
4. DATA-01: vollständigen Löschumfang im Dialog nennen und starke Bestätigung ergänzen.
5. SEC-01: Garmin-E-Mail und private Kalender-URL in die zentrale Redaction aufnehmen.
6. Regressionstests schreiben, die für Startup, Daily, Activity und Fresh-Data **null Remote-Mutationen** beweisen.

### Phase 1 – Vertrauen, Stabilität und wahrgenommene Qualität

1. UI-01 und UI-02 beheben; globalen `hidden`-Vertrag testen.
2. PERF-01/02: State fachlich teilen, Syncstatus separat pollen, Single-Flight einführen.
3. COACH-02: geplante Workouts einmalig, kompakt und begrenzt in den Kontext aufnehmen.
4. SYNC-03: lokale/UTC-Tageslogik korrigieren.
5. REC-01: Maintenance-Gate für Restore und Sync einführen.
6. Playwright-/axe-Smoke-Test in CI aufnehmen.

### Phase 2 – Navigation und Alltagstauglichkeit

1. „Heute“-Ansicht einführen und Check-in aus Profil herauslösen.
2. „Geplant“ in Kalender, Bibliothek und Ziele & Pläne segmentieren.
3. Profil/Integrationen/Datenschutz/Betrieb unter „Mehr“ sauber trennen.
4. Hash-Routing und Browsernavigation ergänzen.
5. Wochenverfügbarkeit strukturiert erfassen und iCalendar-Wiederholungen begrenzt unterstützen.

### Phase 3 – Wartbarkeit und Betrieb

1. `server.py` und `app.js` entlang fachlicher Grenzen modularisieren.
2. Versionierte DB-Migrationen und Foreign-Key-Enforcement einführen.
3. Backup/Export streamen und Readiness erweitern.
4. Streaming/Cancel für Coach-Antworten ergänzen.
5. SBOM, Image-Scan, Signierung, Coverage und statische Analyse ausbauen.

## 17. Abnahmekriterien für die kritischsten Korrekturen

Die drei wichtigsten Änderungen gelten erst als abgeschlossen, wenn automatisierte Tests Folgendes beweisen:

- Ein Startup-, Daily-, Activity-, Full-Resync- oder Coach-Freshness-Lauf führt **keinen** POST/PUT/DELETE zu Intervals.icu aus.
- Bibliotheks- und Wettkampf-Push benötigen jeweils einen eigenen bestätigten API-Aufruf.
- Negierte, fragende oder erklärende Prompts können kein mutierendes Tool ausführen.
- Eine Mutation ist nur mit einem unbenutzten, nicht abgelaufenen und payloadgebundenen Bestätigungs-Token möglich.
- Wiederholung desselben Tokens ändert weder lokal noch remote Daten.
- Die Vorschau nennt Zielsystem, Objektanzahl, Erstellungen, Änderungen und Löschungen.
- Fehler, Timeout oder Seitenreload nach Vorschau führen nicht automatisch zur Ausführung.

## 18. Gesamtbewertung

Die Anwendung ist funktional breit, für den privaten Single-Athlete-Betrieb gut durchdacht und in vielen technischen Sicherheitsdetails stärker als typische lokale PWA-Projekte. Die Architektur hat aber an einem entscheidenden Punkt ihre eigene Produktregel nicht vollständig durchgesetzt: **Lesen, Vorschlagen, lokal speichern und remote synchronisieren sind in einigen Orchestrierungspfaden nicht hart genug getrennt.**

Wenn zuerst die Mutationsfreigaben und impliziten Remote-Syncs korrigiert werden, danach State/Polling und Browserregressionen, ist die Basis tragfähig. Die empfohlenen Navigationsänderungen und Feature-Gaps können anschließend die tägliche Nutzung deutlich verbessern, ohne den privaten, lokalen und eigenständigen Charakter der Anwendung zu verändern.
