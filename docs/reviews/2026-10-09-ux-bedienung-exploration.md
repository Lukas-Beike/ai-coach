# UX- und Bedienungs-Exploration: Findings und Plan (09.10.2026)

## Rahmen

- **Laufzeit:** Disposable Fixture-Container `ai-coach-demo` (`scripts/demo-container.ps1`, Image `ai-coach:local` auf Stand `b42ec71a`). Er lief unter `http://127.0.0.1:8091` mit dem Fixture-Passwort und blockierten Providern; der Coach antwortete mit Fixture-Texten.
- **Ansichten:**
  - Hauptansicht mobile (iPhone 12 Pro, 390×844).
  - Zusätzlich mobile-small (320×568), Tablet, Tablet quer und Desktop.
  - Light- und Dark-Theme.
- **Code:** nur gelesen und vor dem Lesen per `sonar analyze secrets` geprüft. Es gibt keine Code-Änderungen.
- **Testdaten:** zusätzliche Szenarien nur in der Demo-DB des laufenden Containers (siehe Abschnitt 3).
- **Abgrenzung zum Review vom 07.10.:** Folgende Punkte sind bereits in `2026-10-07-architecture-design-ux-review.md` erfasst und laut Ledger umgesetzt; sie werden hier nicht wiederholt:
  - Kontrast erledigter Einheiten (1.2/8.1)
  - `retry_after` (3.1)
  - Upstream-Mapping (3.2)
  - deutsche Texte für `upstream_*` (7.2)

  Die folgenden Befunde sind neu oder betreffen andere Stellen.

## Kurzfassung: die wichtigsten Punkte

1. **P1:** Nicht konfigurierte Provider landen in Retry-Schleifen. Die UI zeigt minutenlang oder endlos „läuft…/wird geladen…“.
2. **P1:** Der Tages-Check-in (Krankheit, Schmerz, Ruhetag) ist seit #415 nicht mehr erreichbar.
3. **P1:** Escape im Login-Dialog hinterlässt eine leere Seite. In der installierten PWA wirkt die App dann tot.
4. **P2:** Kalender und Planung ignorieren Wettkämpfe, Tagesstatus, Krankheit und Kalendermarker bei bestehenden Einheiten.
5. **P2:** Die Aktivitätszuordnung wählt die früheste statt der passenden Aktivität.
6. **P2:** Wochensummen werden zu „–“, sobald einer einzigen Aktivität ein Wert fehlt.
7. **P2:** Der Coach-Planungshinweis ist im Light-Theme unlesbar (Kontrast ≈1,2:1).
8. **P2:** Die Saison-Ansicht zeigt „0 Tage“, „1 Tage“ und „-10 Tage“, archiviert vergangene Rennen nicht und verankert deren Analysefenster an heute.
9. **P2:** Zahlen-, Dauer-, Datums- und Sportformatierung ist querschnittlich uneinheitlich.
10. **P2:** Ein Neustart des Fixture-Containers zerstört Demo-Daten und legt Duplikate an.
11. **P1 (Nachtrag, Abschnitt 7):** Fehler-Toasts sind in beiden Themes unlesbar (Text in Hintergrundfarbe).
12. **P1 (Nachtrag, Abschnitt 7):** „Lokale Daten löschen“ lässt sich nicht abschließen, weil der geforderte Bestätigungstext nirgends genannt wird.
13. **P1 (Nachtrag, Abschnitt 8):** Der „↓“-Button und der Scroll nach dem Senden verfehlen den neuesten Inhalt. Eigene Nachricht, wartende Nachrichten und „Coach arbeitet…“ bleiben hinter Composer und Navigation.
14. **P1 (Nachtrag, Abschnitt 8):** „↓“ fokussiert das Eingabefeld und öffnet auf dem Handy die Tastatur, die die gerade angesprungenen Nachrichten verdeckt.

---

## 1. Findings

### P0

Keine Befunde. Es gab keinen Datenverlust, kein Sicherheitsleck und keinen Bypass der Authentifizierung. Die Markdown-Ausgabe des Coach ist gegen `<img onerror>`, `<script>` und `javascript:`-Links sicher; externe Links bekommen `noopener`.

### P1

#### P1-01 Nicht konfigurierte Provider erzeugen Retry-Schleifen und hängende UI

- **Ort:**
  - Fehlerklassifikation: `backend/sync/refresh.py:220` (`"configur" in message`), `backend/sync/refresh.py:11-22,34-55`.
  - Auslösende Meldungen: `backend/errors.py:6` (`INTERVALS_API_KEY ist nicht konfiguriert.`), `backend/sync/intervals.py:715`, `backend/sync/activity_details.py:89`, `backend/sync/full_resync.py:23`, `backend/sync/external_calendar.py:72`.
  - Frontend: `public/sync-actions.js:102-110` und `public/activity-details.js:247`.
- **Szenario:**
  - **Sync:** Ohne Intervals-Schlüssel tippt man auf „Synchronisieren“.
    - Der Job (`225aa0fa…`) bleibt `queued` mit `error_class=temporary_error`, `available_at` +15 min und bis zu 3 Versuchen.
    - Die UI zeigt 180 s „Synchronisierung läuft…“ und dann eine Timeout-Meldung.
    - Die Datenfrische zeigt „Providerfehler · Nächster Versuch ab …“.
  - **Aktivitätsdetails:** „Aktivität analysieren → Detaildaten laden“ erzeugt einen `activity_details`-Job mit „Intervals.icu ist nicht konfiguriert.“.
    - Die UI zeigt dauerhaft „Detaildaten werden im Hintergrund geladen …“.
    - Das passiert auch bei lokalen Aktivitäten, die nicht von Intervals.icu stammen (Szenario-Yoga).
- **Ursache:** Die Erkennung prüft den englischen Teilstring „configur“, die Meldungen sind aber deutsch („konfiguriert“) und tragen keinen `reason`. Dadurch gilt der Fehler als vorübergehend und wird erneut versucht.
- **Abhilfe:**
  1. An allen Konfigurationsfehlern einen stabilen `reason="not_configured"` setzen und daraus `invalid_configuration` ableiten (nicht wiederholbar).
  2. Das Einreihen vorab mit 409 und `reason` ablehnen, wenn der Provider nicht konfiguriert ist.
  3. Sync- und Detail-Buttons für nicht konfigurierte Provider deaktivieren und auf „Mehr › Anbindungen“ verlinken.
  4. Detaildaten nur für Aktivitäten mit Intervals-Herkunft anbieten.
  5. `waitForSyncJob` soll einen dauerhaften Fehlerzustand sofort beenden, statt 180 s zu warten.
- **Tests:**
  - Unit: tabellengetriebenes `error_code` für jede deutsche Konfigurationsmeldung.
  - API: `POST /api/sync` und `/api/sync/jobs` ohne Schlüssel liefern kein wiederholbares Ergebnis.
  - Playwright: Button-Zustand und Hinweistext.

#### P1-02 Tages-Check-in nicht mehr erreichbar (tote UI seit #415)

- **Ort:**
  - Markup: `public/index.html:110-139` (`#checkinDialog`, `#checkinForm`).
  - Logik: `saveCheckin` in `public/settings.js` und die Historie in `public/views.js:287-331`.
  - Ursache: Commit `44266541` („replace today tab with planned day focus“) hat `openCheckinEditor` entfernt.
  - Doku: `README.md:70`.
- **Szenario:** Die Athletin oder der Athlet möchte Krankheit („Halsschmerzen, 37,8 °C“), Knieschmerz oder einen Ruhetag eintragen. Dafür gibt es keinen Einstieg; nur der Coach-Chat bleibt. `day_status` (rest/pause) erscheint nur in der ebenfalls unerreichbaren Historie.
- **Abhilfe:**
  - Einen Einstieg über einen „Heute“-Chip bzw. die Tageskarte im Kalender und zusätzlich unter Mehr › Profil schaffen.
  - Beim Reaktivieren den Draft-Bug beheben: Ein Klick auf einen älteren Check-in überschreibt den ungespeicherten Entwurf (`public/views.js:287-298,328-331`). Dagegen hilft ein Dirty-Guard.
  - README aktualisieren.
- **Tests:** Playwright speichert einen Check-in; danach zeigt der Kalendertag den Status, und ein Reload behält den Entwurf bzw. die Daten.

#### P1-03 Escape im Login-Dialog führt zu leerer Seite

- **Ort:** `public/auth.js:5-61` (`showAccessibleDialog`; das `cancel`-Event wird nicht abgefangen).
- **Szenario:** Der Login-Dialog ist offen, man drückt Escape. Der Dialog schließt, die App-Shell bleibt verborgen und die Seite ist weiß. Eine installierte PWA hat keine Reload-Schaltfläche, die App wirkt also bis zum erzwungenen Beenden kaputt.
- **Abhilfe:** Für den Login-Dialog `cancel` per `preventDefault()` unterbinden, da er nicht abbrechbar ist. Als Rückfallebene beim `close` ohne Session neu öffnen.
- **Test:** Playwright drückt Escape; der Dialog bleibt sichtbar und fokussiert.

### P2

#### P2-01 Konflikte mit Kalendermarkern werden bei bestehenden Einheiten nicht angezeigt

- **Ort:**
  - Backend: `backend/calendar/external.py:13-37`, `backend/calendar/ical_mapping.py:34-62`, `backend/planning/calendar.py:80-93` (die Prüfung greift nur bei Änderungen).
  - Frontend: `public/plan-views.js:110-131`.
  - Doku: `README.md:117-118` widerspricht `README.md:423`.
- **Szenario:**
  - Geplante Einheiten an diesen Tagen bleiben ohne Hinweis:
    - So 11.10. mit `[NO_TRAINING]` im Titel;
    - Mi 14.10. mit beiden Markern;
    - Camp 15./16.10. mit `[NO_INTENSITY]`.
  - Marker erscheinen als Rohtext („Fixture [NO_TRAINING] recovery marker“).
  - Neue Einheiten an Markertagen lehnt das System dagegen mit 409 ab. Das Verhalten ist also inkonsistent.
- **Abhilfe:**
  - In der Projektion `appointments` die Flags `no_training`, `no_intensity` und `short_only` ausliefern.
  - Bestehende Einheiten, die einen Marker verletzen, mit einem Konflikt-Badge markieren und einen Coach-Anpassungsvorschlag mit Vorschau und Freigabe anbieten.
  - Marker als Badge statt als Rohtext darstellen.
  - Den README-Widerspruch zu Markern in Titel bzw. Beschreibung auflösen.

#### P2-02 Wettkämpfe fehlen im Kalender, und es gibt keine Warnung vor Belastung am oder vor dem Wettkampf

- **Ort:** `public/plan-views.js:110-150` (Tageshinweise enthalten nur Termine und Check-in) und die Saison-Projektion.
- **Szenario:**
  - Heute ist der B-Stadtlauf über 10 km, trotzdem ist für 18:30 ein 58-min-Schwellenlauf geplant.
  - Morgen ist das C-Kriterium, heute ist eine 90-min-Fahrt geplant.
  - Keiner der Wettkämpfe ist im Kalender sichtbar.
- **Abhilfe:**
  - Wettkämpfe als Tageskarte mit Priorität, Sport, Distanz und Ziel zeigen.
  - Konfliktregeln je Priorität: A/B → harte Einheit am Tag selbst oder am Vortag, C → harte Einheit am selben Tag. Daraus einen Hinweis und einen Coach-Vorschlag erzeugen; keine automatische Änderung.

#### P2-03 Tagesstatus und Krankheit wirken sich nicht aus

- **Ort:** `backend/athlete/checkins.py:61-127` (kv `checkin_day_status:<date>`), `public/views.js:295-309` und die Compliance-Berechnung in `public/plan-views.js`.
- **Szenario:**
  - Der 06.10. ist als Ruhetag markiert. Die verpassten Laufintervalle zählen trotzdem als „Nicht absolviert ✕ 0 %“.
  - Heute sind Krankheit, Knieschmerz und „Pause“ eingetragen. Der geplante Schwellenlauf trägt trotzdem keine Warnung; es gibt nur den allgemeinen Gesundheitshinweis des Tages.
- **Abhilfe:**
  - Den Tagesstatus im Kalender anzeigen.
  - An Ruhe- und Pausetagen verpasste Einheiten als „entfallen (Ruhetag)“ werten und aus der Compliance herausnehmen.
  - Bei Krankheit oder Schmerz intensive Einheiten markieren und eine Anpassung über den Coach-Vorschlag anbieten.

#### P2-04 Aktivitätszuordnung wählt die früheste statt der passendsten Aktivität

- **Ort:** `backend/activities/matching.py:92ff` (`_unpaired_activity_match` nach Startzeitabstand; bei Einheiten ohne Uhrzeit gewinnt die früheste Aktivität).
- **Szenario:** Am 08.10. sind 45 min Rad geplant.
  - Zugeordnet wird die 30-min-Fahrt um 12:00 („67 %“).
  - Die exakt passende 45-min-Fahrt um 18:00 erscheint als „Zusätzlich absolviert“.
- **Abhilfe:**
  - Ohne geplante Startzeit nach Ähnlichkeit ranken: zuerst Dauer, dann Belastung, dann Startzeit.
  - Sportfamilien wie Ride/VirtualRide berücksichtigen.
  - Optional eine manuelle Umzuordnung ermöglichen (Feature V3).
- **Test:** parametrisierte Matching-Tabelle mit mehreren Aktivitäten pro Tag.

#### P2-05 Wochensummen kippen auf „–“

- **Ort:** `public/plan-views.js:641-643` (`actual.every((entry) => entry.distance != null)` bzw. `icu_training_load`) und `plannedWeekSummary` (`:305`).
- **Szenario:**
  - Die aktuelle Woche hat 16 Aktivitäten mit km und Belastung. Eine Yoga-Einheit ohne Distanz und Belastung macht trotzdem „Distanz –“ und „Belastung absolviert –“ daraus.
  - Geplanten Einheiten fehlt die Belastung immer, deshalb steht bei „Belastung geplant“ grundsätzlich „–“.
  - In einer Vorwoche ohne Plan steht „Geplant 0:00“.
  - Leere Zukunftswochen werden als „Keine Einheiten“ gelistet.
  - Distanz erscheint mit Dezimalpunkt („444.8 km“).
- **Abhilfe:**
  - Teilsummen anzeigen, etwa „444,8 km · ohne 1 Aktivität“.
  - Sportarten ohne Distanz bei der Distanz ignorieren.
  - Geplante Belastung schätzen (gleiche Logik wie P2-08) oder die Zeile ausblenden.
  - „Geplant –“ statt „0:00“.
  - Leere Zukunftswochen zusammenfassen.

#### P2-06 Kontrast: Coach-Planungshinweis im Light-Theme unlesbar; Kopf geplanter Einheiten im Dark-Theme

- **Ort:**
  - `public/styles.css:107` (`--planning-danger-ink: #ffd9d5`) und `:786`. Der Light-Block ab `:147` überschreibt das Token nicht.
  - Dark-Theme: Kopf geplanter Einheiten.
- **Szenario:**
  - Im Light-Theme steht der Hinweis „Deine Planung braucht eine Anpassung“ in #ffd9d5 auf Hellrosa (Kontrast ≈1,2:1).
  - Im Dark-Theme hat der Kopf der geplanten Einheit „Laufen · 18:30“ einen Kontrast von ≈3,9:1. Der Fix 8.1 deckt nur erledigte Einheiten ab.
- **Abhilfe:**
  - Das Token im Light-Block überschreiben (dunkles Rot, Kontrast ≥4,5:1).
  - Dasselbe für geplante Einheiten tun.
  - Die Token-Paar-Prüfung in `tests/test_css_design_tokens.py` und die axe-Spec auf den Coach-Hinweis und geplante Karten erweitern.

#### P2-07 Saison: Wettkampfstatus, Archiv und Analysefenster

- **Ort:** `public/plan-views.js:142`, `public/analysis.js:1087` (`${event.days_until} Tage`) und `backend/planning/season_preparation.py`.
- **Szenario:**
  - Es erscheinen „0 Tage“ (heute), „1 Tage“ und „-10 Tage“.
  - Das vergangene A-Rennen steht oben und wird nicht archiviert.
  - Sein Vorbereitungsfenster ist an heute statt am Renndatum verankert und zeigt deshalb dieselben Werte wie das heutige Rennen.
  - Alle Events sind aufgeklappt, die Seite ist ≈11.400 px hoch. Die Diagramme gleichen sich je Sportart.
  - Einige Begriffe sind englisch: „Ride“, „confirmed local competition“, „Intervals.icu recorded activities“ und „cached activity analyses“.
  - Die Wochendefinition ist rollend (Sa–Fr), im Kalender dagegen Mo–So.
- **Abhilfe:**
  - Labels „Heute“, „Morgen“, „in 1 Tag“ und „vor 10 Tagen“ verwenden.
  - Einen Archivbereich für vergangene Wettkämpfe anlegen, mit optionalem Ergebnis (Ist-Zeit gegenüber Ziel).
  - Das Analysefenster relativ zu `event_date` berechnen.
  - Nur den nächsten Wettkampf aufklappen.
  - Die englischen Begriffe übersetzen.
  - Eine einheitliche Wochendefinition verwenden.

#### P2-08 Saison-Szenariovergleich scheitert an fehlender Planbelastung

- **Ort:** `backend/planning/season_preparation.py:259`.
- **Szenario:** Der Vergleich bricht mit „Mindestens einer geplanten Einheit fehlt die Belastung.“ ab. Nutzende erfahren nicht, welche Einheit betroffen ist, und geplanten Einheiten fehlt die Belastung grundsätzlich. Die Faktoreingabe zeigt „0.8“ mit Punkt.
- **Abhilfe:**
  - Die Belastung aus Dauer und Zielintensität schätzen und als „geschätzt“ kennzeichnen.
  - Sonst die betroffenen Einheiten nennen und verlinken.
  - Kommaeingabe akzeptieren.

#### P2-09 Wettkämpfe sind nicht verwaltbar, Duplikate bleiben unerkannt

- **Ort:** Laut `docs/api-routes.md` gibt es nur `PUT /api/athlete-context`; dazu `backend/planning/competition_service.py`.
- **Szenario:** „Fixture cycling target“ existiert zweimal und erscheint doppelt. Bearbeiten, Löschen oder Archivieren geht nur über den Coach.
- **Abhilfe:**
  - Bearbeiten, Löschen und Archivieren in der Saison-Ansicht anbieten, mit Änderungsverlauf und Undo.
  - Vor dem Speichern bei gleichem Namen, Datum und Sport warnen.

#### P2-10 Ernährung: Teilsummen und Mahlzeitzeiten

- **Ort:** `public/nutrition.js:290`, `backend/nutrition/models.py:34-44` (`meal_type_from_hour`), `:144-192` (Standardzeit = jetzt) und `backend/nutrition/diary.py`.
- **Szenario:**
  - Ein Eintrag ohne Makros („Kantine 750 kcal“) macht aus allen Tagesmakros „– g · unvollständig“.
  - Einträge ohne Uhrzeit bekommen die aktuelle Uhrzeit, der Mahlzeittyp wird daraus abgeleitet. Vergangene Tage zeigen dadurch „19:21 Abendessen“ für einen Porridge.
  - Eine Mahlzeit um 23:45 wird zum „Snack“.
- **Abhilfe:**
  - Bekannte Teilsummen zeigen und „1 Eintrag ohne Makros“ ergänzen.
  - Die Uhrzeit optional speichern, ohne eine Zeit vorzutäuschen.
  - Den Mahlzeittyp explizit wählbar machen.
  - Eine nötige Schemaänderung nur mit versionierter Migration und Upgrade-Test gemäß Release-Vertrag umsetzen.

#### P2-11 Offline-Fehler roh, Banner verspricht nicht vorhandenes Puffern

- **Ort:** `public/api.js:58,104-108`, `public/shared.js:328-336`, `public/sync-status.js:232` und `public/state-loader.js:107,114`.
- **Szenario:** Offline erscheint „Failed to fetch“. Der Banner verspricht zwischengespeicherte Änderungen, die es nicht gibt.
- **Abhilfe:** `network_error` auf einen deutschen Text abbilden. Den Bannertext an das tatsächliche Verhalten anpassen oder eine echte Outbox bauen (Feature V9).

#### P2-12 Logout oder 401 verwirft wartende Chat-Nachrichten

- **Ort:** `public/auth.js:18-19,172-176`, `public/shared.js:237-239` und `public/coach.js:249-258`.
- **Abhilfe:** Die Warteschlange in `sessionStorage` sichern. Ein Ablauf der Sitzung (401) bewahrt Warteschlange und Entwurf und bietet sie nach dem erneuten Login zur Wiederaufnahme an. Ein explizites Abmelden löscht beides. Beide Pfade werden getrennt getestet (siehe V22). Einträge mit Anhang (GPX, FIT, Bild) werden nie automatisch gesendet: Nach einem Neuladen erscheinen sie nur als bearbeitbarer Entwurf mit dem Hinweis „Anhang erneut hinzufügen“.

#### P2-13 Abmelden: irreführender Text, versteckter Ort und technischer Login-Text

- **Ort:** `public/index.html:345-374`, `:372` und `:404`.
- **Szenario:**
  - „Abmelden“ liegt in „Datenschutz & Verbrauch“.
  - Der Text daneben lautet: „Die Datenbank bleibt als verschlüsselte Datei bestehen; ihr Inhalt wird geleert.“ Ein Logout leert aber nichts in der Datenbank.
  - Der Login-Text lautet „Gib das im Container gesetzte APP_PASSWORD ein.“
- **Abhilfe:**
  - „Abmelden“ als eigenen Eintrag in der Mehr-Hauptliste führen.
  - Neuer Text: „Du wirst auf diesem Gerät abgemeldet. Deine Daten bleiben verschlüsselt gespeichert.“
  - Neuer Login-Text: „Gib dein App-Passwort ein.“

#### P2-14 mobile-small (320×568): Eingabefeld des Coach zu schmal

- **Szenario:**
  - Plus, Mikrofon und Senden drücken die Textarea auf ≈80 px.
  - Der Platzhalter bricht um und wird abgeschnitten, eine native Scrollbar ist sichtbar.
  - Eingabefeld und Bottom-Navigation belegen ≈180 px.
- **Abhilfe:**
  - Unter 360 px bündelt „+“ die Zusatzaktionen.
  - Das Mikrofon erscheint nur bei leerem Feld, Senden nur mit Text.
  - Einen kürzeren Platzhalter verwenden und das Feld automatisch wachsen lassen.
  - Bis zwei Zeilen `overflow-y: hidden` setzen.

#### P2-15 Analyse: Laufprognosen und Effizienz fehlerhaft

- **Ort:** `public/performance-view.js:261` (`#performancePredictions`) und `public/analysis.js:892`.
- **Szenario:**
  - Die Prognosetabelle enthält nur „Gewicht | 72 kg | Garmin Connect“, keine Prognosen.
  - Die Ausdauer-Effizienz beim Laufen ist eine flache Linie bei 0. Werte um 0,02 werden gerundet oder fehlende Werte als 0 dargestellt.
  - Rad (02.–09.10.) und Lauf (18.07.–07.10.) zeigen unterschiedliche Zeiträume.
- **Abhilfe:**
  - Das Gewicht aus der Prognosetabelle entfernen und einen Leerzustand mit Grund zeigen.
  - Lücken statt Nullen darstellen, Skalierung und Präzision anpassen.
  - Gleiche Zeiträume verwenden.

#### P2-16 Info-Buttons zu klein, Popover losgelöst

- **Szenario:**
  - `button.analysis-legend-info` ist ≈4,5×29 px groß.
  - Das Popover erscheint bei (0,0) statt am Button.
  - Das „i“ klebt am Text, der Screenreader-Text lautet „Laufeni“.
- **Abhilfe:**
  - Trefferfläche von 44×44 px.
  - Anker-Positionierung mit Fallback.
  - Abstand und `aria-label` „Erklärung zu Laufen“.

#### P2-17 Formatierung querschnittlich uneinheitlich

- **Ort:**
  - `public/shared.js:301` (`toFixed(1)`)
  - `public/activity-details.js:51,109,157`
  - `public/analysis.js:865`
  - `public/nutrition.js:200`
  - `public/views.js:274`
- **Szenario:**
  - Dezimalpunkte: „252.5 W“, „216.88 W“, „6.0 km“, „444.8 km“, „42.5%“.
  - Tausendertrennung fehlt („7560 kcal“ gegenüber „1.960 kcal“); „1.033 km“ ist mehrdeutig.
  - Dauern in vielen Varianten: „2:10:00“, „0:00“, „40:00“, „40 Min.“, „90 min“, „7:16 h“, „35:35:00“.
  - Datumsangaben in englischem Format („Oct 9, 2026, 7:21 PM“) oder als ISO-Zeitstempel („2026-10-09 07:10:00“).
  - Das Datumsfeld zeigt das US-Format „10/09/2026“.
  - Englische Sport- und Fachbegriffe: Ride, Run, VirtualRide, Yoga, „Endurance Score“, „Running Tolerance“.
- **Abhilfe:**
  - Ein gemeinsames Modul `public/format.js` für Zahl, Distanz, Dauer, Datum, Uhrzeit und Sportname, auf Basis von `Intl` mit `de-DE` und der Profil-Zeitzone.
  - Eine einzige Dauer-Konvention, zum Beispiel „45 min“ / „1:05 h“.
  - Node-Tests für die Hilfsfunktionen.
  - Ein Architekturtest, der neue `toFixed(` und `toLocaleString()` ohne Locale in `public/` verbietet.

#### P2-18 Chat-Status wird auf allen Tabs alle ≈5 s abgefragt

- **Ort:** `public/coach.js:163`.
- **Szenario:** Das Polling läuft auch außerhalb des Coach-Tabs und im Leerlauf. Es kostet Akku und flutet das INFO-Log (dazu kommen Favicon-Requests).
- **Abhilfe:**
  - Nur bei laufendem Coach-Job und sichtbarem Tab abfragen (`visibilitychange`), sonst `/api/state/events` (SSE ist vorhanden) nutzen.
  - Statusabfragen auf DEBUG loggen.

#### P2-19 Weitere Befunde aus dem Frontend-Code-Review

- Extraktionswarnungen der Ernährung werden ausgeblendet, sobald eine numerische Konfidenz vorliegt (`public/nutrition.js:482,488-490`). Abhilfe: Warnungen immer als Checkliste zeigen.
- Veraltete oder teilweise synchronisierte Provider lösen `role=alert` „manuelles Eingreifen“ aus (`public/sync-status.js:248,284-307`). Abhilfe: `role=status`; „alert“ nur bei echtem Handlungsbedarf.
- Das Kalenderwetter wird nach einem Sync möglicherweise nicht aktualisiert, weil der Snapshot `state.data.weather` auslässt (`public/plan-views.js:542-544,677`). Das muss noch verifiziert werden.

#### P2-20 Fixture-Neustart zerstört Demo-Daten (Tooling)

- **Ort:** `e2e/fixture_runtime.py:348-354`, `:387-470`, `:569-576` und `:1388-1397`.
- **Szenario:** Ein Neustart mit `FIXTURE_AUTO_SEED=1` (zum Beispiel mit `-Persist`) ruft `seed_training_features()` ohne Schutz auf. Reproduziert.
  - Der Snapshot wird ersetzt: Die 90 Wave-2-Aktivitäten sind weg, die Wellness-Daten zurückgesetzt.
  - Die kv-Einträge der Ausrüstung werden gelöscht.
  - Ein weiterer „Fixture cycling target“ wird angelegt.
  - Seed-Version „5“ verhindert die Wiederherstellung.
  - Der Kommentar „Both seeds are idempotent“ ist falsch.
- **Abhilfe:** siehe Abschnitt 4.

### P3

| Bereich | Befund | Ort | Abhilfe |
| --- | --- | --- | --- |
| Kalender | Einheiten ohne Startzeit zeigen eine fiktive Uhrzeit „00:00“. | Kalenderkarte | Uhrzeit weglassen |
| Kalender | Metadaten stehen doppelt („Laufen · 08:00 / 40:00“ und „Laufen · 08:00 · 40:00“); `span.planned-meta` ist abgeschnitten. | Kalenderkarte | einmal ausgeben, umbrechen statt abschneiden |
| Kalender | „Wetter fehlt“ steht an jedem Tag; der Grund steht nur im `title`. | `public/plan-views.js:579` | einen Hinweis oben mit Link zum Profilstandort |
| Kalender | Jede Aktivität ohne Plan heißt „✓ Zusätzlich absolviert“. | `public/plan-views.js:70` | „Absolviert“; „zusätzlich“ nur, wenn am Tag ein Plan existiert |
| Kalender | Leere Zukunftswochen werden einzeln gelistet. | Wochenliste | zusammenfassen („3 Wochen ohne Plan“) |
| Kalender | Die Fehlermeldung „verletzt eine aktuelle Kalenderbeschränkung“ nennt weder Datum noch Marker. | `backend/planning/planned_unit_service.py:230-247,496` | Datum und Marker nennen |
| Kalender | Tablet und Desktop zeigen eine gestreckte Spalte (Karten ≈770 px), keine Wochenansicht; die Tablet-Leiste zeigt nur Icons. | Layout ≥768 px | Wochenraster (Feature V6), Beschriftung ab 1024 px |
| Kalender | Im Dark-Theme erscheint das Profil der Fueling-Fahrt mit absoluten Watt als grauer Verlaufsblock. | Workout-Profil | Strukturgrafik für Watt-Ziele oder Platzhaltertext |
| Bibliothek | „0 Einheiten“ ohne hilfreichen Leerzustand. | `public/plan-views.js:740` | Erklärung und Aktion „Coach um Vorlage bitten“ |
| Aktivität | Kopfzeile „Yoga · 2026-10-09 07:10:00 · 25 min“: ISO-Zeitstempel, englischer Sportname (der Kalender sagt „Andere“), „25 min“ gegenüber „25:00“. | `public/activity-details.js:109` | Format-Hilfen (P2-17) |
| Aktivität | Das Feld „Abweichungsgrund“ erscheint auch bei ungeplanten Aktivitäten. | `public/activity-details.js:81` | nur bei zugeordneter Einheit zeigen |
| Coach | Markdown-Tabellen erscheinen als Rohtext mit Pipes; eine verschachtelte Liste wird zu einer separaten Liste. | `public/views.js:24-41` | sichere Tabellen- und Verschachtelungsunterstützung per DOM-API |
| Coach | Der versteckte Status bleibt im Leerlauf auf „Coach arbeitet an deiner Antwort…“; nur der Stream-Abschluss setzt „Antwort fertig.“. | `public/coach.js:304,724-736` | bei jedem Wechsel in den Leerlauf setzen oder leeren |
| Coach | Live-Regionen werden per `hidden` umgeschaltet und dadurch nicht angesagt. | `public/coach.js:612-618,731-736,997-1002` | Region dauerhaft sichtbar lassen, nur den Text ändern |
| Ernährung | Keine Plausibilitätsprüfung (eine Pizza mit 4.500 kcal wird ohne Rückfrage übernommen) und keine Bilanz (7.560 kcal Aufnahme gegenüber 1.960 kcal Verbrauch). | Tagebuch | Warnschwelle und Bilanz (Feature V5) |
| Ernährung | Die Klasse `.visually-hidden` ist nicht definiert; das Label „Nährwerttabelle auswählen“ ist dadurch sichtbar. | `public/index.html:180`, `public/styles.css:189` | `.sr-only` verwenden |
| Ernährung | Der Untertitel „Erfassen und ändern über deinen Coach“ widerspricht „Produkt manuell erfassen“; der Leerhinweis der Produkte steht doppelt und schon vor jeder Suche; Produktbuttons sind unterschiedlich groß. | Produkte | Text anpassen, Hinweis erst nach einer Suche, einheitliche Buttons |
| Ernährung | Fueling liegt unter „Meine Mahlzeiten“; „90 min“ steht neben „90 Min.“. | Mahlzeiten | eigener Abschnitt, Format-Hilfen |
| Analyse | Endurance Score und Running Tolerance tragen die Einheit „Belastungspunkte“; Ride und VirtualRide stehen in „Beste Fenster“ als identische Doppelzeilen. | Leistung | Einheit korrigieren, Zeilen zusammenführen |
| Analyse | Der Trainingsfokus basiert auf 3 Garmin-Einheiten (≈2 h in 28 Tagen bei ≈7 h pro Woche Training); die Abdeckung wird nicht kommuniziert, der Tooltip ist technisch. | Belastung | Abdeckungshinweis in Klartext |
| Analyse | Die Wochenachsen sind uneinheitlich (Kalenderwoche gegenüber rollender Woche); die laufende Teilwoche fließt in Mittelwerte ein. | Belastung, Körper | eine Definition, Teilwoche kennzeichnen |
| Analyse | Der Zeitraum-Umschalter markiert die Auswahl nur mit einer Outline; die Labels im Schlafdiagramm („7:00“, „7:30“) passen nicht zu „Ø 7:14 h“; der Bereich Erholung zeigt keine subjektiven Check-in-Daten. | Erholung | Segment-Stil, Label an der Ø-Linie, Feature V7 |
| Mehr | „Gemeinsamer Kalender: Nicht konfiguriert“ steht zusammen mit „Letzter Erfolg“; „Aktiv Aktiviert“ ist doppelt; der Sync-Zustand ist inkonsistent; „Anbindungen“ braucht zwei Schritte. | Anbindungen, Datenschutz | Zustände bereinigen |
| Mehr | Texte verweisen auf den Tab „Plan“, der jetzt „Kalender“ heißt; „-1 = alle verfügbaren Daten“ ist zu technisch. | `public/index.html:292,301` | Begriffe und Text anpassen |
| Mehr | Ausrüstung: „1 zugeordnete Einheiten“, „42.5%“/„136.7%“ und zwei Gruppen „Archivierte Ausrüstung“. | Ausrüstung | Pluralisierung, Format, Gruppierung |
| Mehr | „Coach & Modell“ zeigt rohes JSON mit Sprachmix; der Änderungsverlauf zeigt rohe Feldnamen („category, course_profile, …“). | Coach, Datenschutz | Klartext-Zusammenfassung |
| Mehr | Profil: Die Mehrfachauswahl zeigt mobil einen Strg/Cmd-Hinweis; die Zusammenfassung lautet roh „Cycling, Running“. | Profil | Checkbox-Chips, deutsche Namen |
| Global | Der Setup-Banner („Einrichtung nötig: Intervals.icu-API-Schlüssel“) belegt ≈70 px, lässt sich nicht schließen und bietet keine Aktion; auf „Mehr“ fehlt er. | alle Tabs | schließbar, Link „Jetzt einrichten“, einheitlich |
| Global | Fehlt die Job-ID, erscheint trotzdem ein Erfolgstoast. | `public/sync-actions.js:28-31,45-48,63-66` | wie `syncNow` die ID prüfen |
| Global | Segment-Controls haben nur `min-height: 40px`. | `public/styles.css:243` | 44 px |
| Global | Begriffe uneinheitlich (Schmerz/Muskelkater, rohe Sport-Keys); `#calendarHorizonHint` fehlt; `aria-label` „Hauptnavigation“ ist doppelt vergeben. | `public/views.js:274`, `public/index.html:29,390` | Glossar, eindeutige Labels |
| Global | iOS: Der Backup-Download widerruft die URL sofort. | `public/settings.js:94-95,190-191` | `revokeObjectURL` verzögern |
| Global | Das Manifest hat nur ein SVG-Icon (maskable), kein PNG und kein `apple-touch-icon`; ein Fehlschlag bei Benachrichtigungen blockiert den erneuten Versuch. | Manifest, `public/notifications.js:25-32` | PNG-Icons, erneuten Versuch erlauben |
| Global | Tote Platzhalter. | `public/forms.js:1`, `public/index.html:36-39,317-318` | entfernen |
| Backend-Texte | Umlaute als Ersatzschreibung („Wiederholungsbloecke“, „enthaelt“, „Ungueltige …“). | `backend/activities/workout_text.py:269`, `backend/coach/proposal_creation.py:44`, `backend/coach/proposal_validation.py:204`, `backend/coach/receipt_reads.py:42`, `backend/planning/state_service.py:66`, `backend/planning/library_service.py:231` | echte Umlaute, Test auf `ae/oe/ue` in Nutzertexten |
| Doku | README nennt den Check-in noch als nutzbar (`:70`); `:117-118` widerspricht `:423` bei den Markern; Aussagen zur Erholungs-Auswahl widersprechen sich. | `README.md` | mit den Fixes aktualisieren |

---

## 2. Verbesserungs- und Feature-Vorschläge

| # | Vorschlag | Nutzen | Hinweise zum Vertrag |
| --- | --- | --- | --- |
| V1 | **„Heute“-Chip mit Schnell-Check-in** (Tagesform, krank, Schmerz, Ruhetag/Pause) direkt im Kalender | Behebt P1-02 und speist P2-03; Erfassung in 5 s | Explizite UI-Aktion; der Coach ändert nichts still |
| V2 | **Tagesbadges im Kalender:** Wettkampf (A/B/C), Tagesstatus, Kalendermarker und Konflikte | Planung auf einen Blick; deckt P2-01 bis P2-03 ab | Konfliktauflösung nur über Coach-Vorschlag mit Vorschau und Freigabe |
| V3 | **Best-Fit-Zuordnung und manuelles Umzuordnen** („Diese Aktivität gehört zu …“) | Korrekte Compliance bei mehreren Einheiten pro Tag | Lokaler Override; Schema nur mit Migration |
| V4 | **Wettkampfverwaltung:** bearbeiten, löschen, archivieren, Duplikatwarnung, Ergebnis erfassen (Ist gegenüber Ziel) | Saubere Saison; Rückblick | Änderungsverlauf und Undo; gilt als bestätigte, autoritative Daten |
| V5 | **Energiebilanz und Kohlenhydratziel** pro Tag (Aufnahme, Verbrauch, Trainings-Fueling), Teilsummen, Plausibilitätswarnung | Ernährung wird handlungsleitend | Quellen labeln (Garmin, geschätzt) |
| V6 | **Wochenraster ab Tablet und Desktop** (7 Spalten, Tageskarten kompakt) | Nutzt den Platz; Vergleich Plan/Ist pro Woche | Asset-Version und Service-Worker-Cache bumpen |
| V7 | **Subjektive Erholung in der Analyse** (Stress, Muskelkater, Motivation, Krankheitstage neben HRV und Schlaf) | Verbindet Gefühl und Messwerte | Daten nur lokal, Kontext für den Coach mit Quellenlabel |
| V8 | **Gemeinsame Format-Hilfen** (`format.js`) und ein Glossar deutscher Sport- und Fachbegriffe | Behebt P2-17 und viele P3 dauerhaft | Node-Tests und Architekturtest |
| V9 | **Ehrliches Offline-Verhalten:** `network_error`-Mapping und optional eine Outbox für Check-in und Ernährung | Kein „Failed to fetch“, keine falschen Versprechen | Outbox darf keine Remote-Writes auslösen |
| V10 | **Chat-Warteschlange über 401 hinweg retten**, `#chatQueueStatus` sichtbar | Keine verlorenen Nachrichten bei abgelaufener Sitzung | Kein Speichern sensibler Inhalte über die Sitzung hinaus; explizites Abmelden löscht die Warteschlange (siehe P2-12, V22) |
| V11 | **Dirty-Guard-Helfer** für alle Formulare (Check-in, Profil, Ernährung) | Kein stilles Überschreiben von Entwürfen | Router hat bereits einen Guard; vereinheitlichen |
| V12 | **Saison-Zeitstrahl** (Wettkämpfe mit Phasen, eingeklappte Karten, Archiv) | Überblick statt 11.000 px Scrollen | – |
| V13 | **Provider-bewusste Aktionen:** Buttons nur für konfigurierte Provider; Setup-Banner schließbar mit Direktlink | Behebt die Ursachen von P1-01 in der UI | – |
| V14 | **Sichere Markdown-Tabellen** im Coach (DOM-basiert, horizontal scrollbar) | Trainingswochen als Tabelle lesbar | Weiter keine HTML-Durchreichung |
| V15 | **Chat-Status per SSE** statt Polling | Akku, Logs | `/api/state/events` existiert |
| V16 | **Konkrete Konfliktmeldungen** (Datum, Marker, Vorschlag „auf X verschieben?“) | Weniger Rätselraten bei 409 | – |

---

## 3. Testdaten-Szenarien (in der Demo-DB angelegt)

Die Szenarien liegen nur in der Demo-DB des laufenden Containers `ai-coach-demo`, nicht im Repository. Das Skript liegt außerhalb des Repositorys unter `%TEMP%\coach-scenarios\scenarios.py`; Check-ins, Ernährung und Chat wurden über die authentifizierte API der Seite angelegt.

Ein Neuerstellen des Containers ohne `-Persist` verwirft die Daten. Ein Neustart zerstört wegen P2-20 die angehängten Aktivitäten.

| Szenario | Daten (heute = Fr 09.10.2026) | Aufgedeckt |
| --- | --- | --- |
| Wettkampf heute und morgen | B-Stadtlauf 10 km heute (Ziel 45:00), C-Kriterium am 10.10. | P2-02, P2-07 |
| Vergangener Wettkampf | A-Halbmarathon am 29.09. | P2-07 („-10 Tage“, Analysefenster) |
| Sehr langer Wettkampfname | Großglockner-Radmarathon am 08.12. (B) | Umbrüche geprüft: kein Überlauf |
| Verpasste Einheit am Ruhetag | Laufintervalle (PACE) am 06.10., Check-in `day_status=rest` | P2-03 |
| Krafteinheit als Text | WeightTraining am 07.10., nicht absolviert | Darstellung Text-Workout |
| Zuordnungs-Mehrdeutigkeit | Plan 45 min Rad am 08.10.; Fahrten um 12:00 (30 min) und 18:00 (45 min); dazu Schwimmen „Hallenbad“ | P2-04 |
| Krank, Schmerz, Pause | Check-in heute: Halsschmerzen 37,8 °C, Knie, Stress 9, Pause, lange Notizen; Schwellenlauf 18:30 geplant | P2-03, P2-06 (Hinweis) |
| Lange Namen | Rad-Einheit mit sehr langem Namen am 20.10.; Aktivität mit HTML-artigem und unumbrechbarem Namen | Escaping in Ordnung, Umbruch in Ordnung |
| Schwimmen strukturiert | Technik-Schwimmen am 21.10. | Text-Workouts für Ausdauer werden abgelehnt (Syntaxhinweis unten) |
| Bibliothek | 3 undatierte Vorlagen (Sweet Spot, Lockerer Lauf HR, Kraft) | Bibliothek nicht mehr leer |
| Aktivität ohne Distanz und Belastung | Yoga heute 07:10 | P2-05, P1-01 (Detaildaten), Aktivitäts-Kopfzeile |
| Belastungs-Ausreißer | Brevet 300 am 03.10. (11:42 h, Belastung 512) | Skalen, Dauerformat |
| Markdown und XSS im Chat | Tabelle, Code, `<img onerror>`, `<script>`, `javascript:`-Link, langes Wort, verschachtelte Liste, Zitat | Rendering sicher; Tabelle und Verschachtelung fehlen |
| Ernährung extrem und unvollständig | 07:15 Haferbrei, 12:30 Kantine ohne Makros, Gel mit 0 kcal, 23:45 Pizza mit 4.500 kcal und langer Beschreibung | P2-10, P3 Ernährung |

---

## 4. Empfehlungen für den Fixture-Seed (`e2e/fixture_runtime.py`)

### 4.1 Bugfix für Neustarts (P2-20)

1. Einen eigenen Versionsschlüssel für `seed_training_features()` anlegen (zum Beispiel `training_features_seed_version`). In `initialise_fixture()` die Funktion nur noch über `seed_preview_demo()` aufrufen, nicht doppelt.
2. Den Wettkampf „Fixture cycling target“ (`:569-576`) wie in `_fixture_wave2_competitions` per Name und Datum absichern.
3. Einen vorhandenen Snapshot mit Wave-2-Daten nie ersetzen, sondern zusammenführen. `/api/fixture/activity` sollte ebenfalls zusammenführen statt ersetzen.
4. Den Kommentar `:350-351` korrigieren.
5. Regressionstest ergänzen: `initialise_fixture()` zweimal mit temporärem Datenverzeichnis ausführen; Anzahl der Aktivitäten, Wettkämpfe, Einheiten und Ausrüstungsschlüssel bleibt gleich.

### 4.2 Neue deterministische Szenarien (Seed-Version „6“ mit Upgrade von „5“)

- Die Szenarien aus Abschnitt 3, relativ zu `today`. Ruhetag und Krankheit über `checkin().save`, Mahlzeiten mit `meal_time`.
- Vergangene Einheiten in drei Zuständen: zugeordnet, teilweise erfüllt und verpasst. Mindestens ein Tag mit zwei gleichartigen Aktivitäten für die Zuordnung.
- Geplante Einheiten mit Belastung, damit die Wochensumme und der Saison-Vergleich testbar werden.
- Konflikt-Einheiten an Markertagen, die direkt gespeichert werden (die Prüfung greift nur bei Änderungen), plus je ein Beispiel für `[SHORT_ONLY]` und `[NO_INTENSITY]`.
- Ein Chat-Verlauf mit Markdown-Tabelle für die Rendering-Regression.
- Getrennte E2E-Fixtures für „Provider nicht konfiguriert“ und „Provider konfiguriert, aber offline“, um P1-01 zu testen.

### 4.3 Hinweise zur Workout-Syntax für Seeds

- Ein PACE-Ziel braucht den Schrittzusatz „Pace“ (`- 15m Z2 Pace`), ein HR-Ziel braucht „HR“.
- Wiederholungsblöcke müssen durch Leerzeilen getrennt sein.
- Ausdauersportarten, auch Schwimmen, brauchen strukturierte Schritte. Nur WeightTraining akzeptiert Fließtext.
- `normalize_workout` lehnt Daten vor `today-1` ab. Für vergangene Einheiten braucht es ein fiktives `today` oder einen eigenen Seed-Pfad.
- `PlannedUnitService.create` lehnt Markertage mit 409 ab. Konfliktszenarien müssen deshalb direkt gespeichert werden.

---

## 5. Umsetzungsplan (PR-Schnitt)

| Reihenfolge | PR-Titel (Conventional Commits) | Inhalt | Nachweis |
| --- | --- | --- | --- |
| 1 | `fix(sync): treat unconfigured providers as non-retryable` | P1-01 im Backend: `reason`, Klassifikation, Ablehnung vor dem Einreihen | Unit- und API-Tests mit gemockten Providern |
| 2 | `fix(ui): disable provider actions without configuration` | P1-01 im Frontend, V13, Banner | Playwright mobile und desktop; Asset- und Service-Worker-Bump |
| 3 | `fix(auth): keep login dialog open on Escape` | P1-03 und P2-13 (Texte, Ort von Abmelden) | Playwright für Login, Escape und Logout |
| 4 | `feat(ui): restore daily check-in from calendar` | P1-02, V1, Dirty-Guard | Playwright; README:70 |
| 5 | `feat(calendar): show competitions, day status and marker conflicts` | P2-01, P2-02, P2-03, V2 | Unit-Tests der Projektion, Playwright, README:117/423 |
| 6 | `fix(activities): match date-only units by best fit` | P2-04 | parametrisierte Zuordnungstests |
| 7 | `fix(ui): partial week totals and shared formatters` | P2-05, P2-17, V8 | Node-Tests und Architekturtest |
| 8 | `fix(ui): planning notice contrast in light theme` | P2-06 | Token-Paar-Test, axe in beiden Themes |
| 9 | `fix(season): relative labels, archive and event-anchored windows` | P2-07, P2-08, V12 | Unit- und Playwright-Tests |
| 10 | `fix(nutrition): partial macro totals and honest meal times` | P2-10 (ggf. Migration und Upgrade-Test nach Release-Vertrag) | Migrationstest mit eingefrorenem Schema, falls das Schema geändert wird |
| 11 | `fix(ui): offline errors and chat queue on 401` | P2-11, P2-12, V9, V10 | Playwright mit gemocktem Offline und 401 |
| 12 | `fix(ui): compact composer on small screens` | P2-14 | Playwright mobile-small |
| 13 | `perf(coach): poll chat status only while active` | P2-18, V15 | Unit- und Playwright-Tests |
| 14 | `fix(analysis): predictions, efficiency and info popovers` | P2-15, P2-16 | Playwright tablet und desktop |
| 15 | `test(e2e): idempotent fixture seed with new scenarios` | P2-20, Abschnitt 4 | Regressionstest für den doppelten Start |
| 16 | `fix(ui): German copy and P3 polish` | P3-Tabelle in kleinen Paketen | jeweils betroffene Playwright-Projekte |

Für jedes Frontend-PR gilt: Asset-Querys in `public/index.html` und den Cache in `public/service-worker.js` bumpen. Jede Schemaänderung (V3, V4, ggf. P2-10) braucht eine versionierte, transaktionale Migration mit eingefrorenem Vorgänger-Schema, einen Rollback-Test und einen Test für den Neustart mit demselben Build.

---

## 6. Prüfumfang und Grenzen

- **Manuell geprüft:**
  - alle Tabs und Unterseiten in der mobilen Ansicht
  - mobile-small, Tablet und Desktop ohne horizontalen Überlauf
  - Light- und Dark-Theme
  - Login, Logout und Escape
  - Coach: Enter/Shift+Enter und Markdown-Sicherheit
  - Ernährung: Erfassen und Ändern
  - Aktivitätsdetails
- **Nicht geprüft:**
  - echte Provider (blockiert)
  - Mikrofon und Benachrichtigungen
  - echte PWA-Installation und Offline-Cache
- **Nicht ausgeführt:** Playwright- und Unit-Suites, weil kein Code geändert wurde.
- **Offen:** P2-19 (Wetter nach Sync) ist nur statisch belegt und muss mit einem Wetter-Fixture verifiziert werden.

---

## 7. Nachtrag: zweite Design- und Usability-Runde

Gleiche Umgebung wie oben (Demo-Container, iPhone 12 Pro hoch und quer, Light- und Dark-Theme, 150 % Schriftgröße). Aufgenommen ist nur, was im Browser reproduziert oder im Code eindeutig belegt wurde. Punkte aus den Abschnitten 1 und 2 (zum Beispiel P2-16 Info-Buttons, Segment-Höhe 40 px) werden nicht wiederholt.

### 7.1 P1

#### N-01 Fehler-Toasts sind unlesbar

- **Ort:**
  - `public/styles.css:1111`: `.error { color: var(--danger-ink) !important; }` greift auch auf `#toast.error`.
  - `public/styles.css:1112-1114` und `public/shared.js:197-205`.
- **Szenario:**
  - Jeder Fehler-Toast ist betroffen, zum Beispiel ein fehlgeschlagener Sync, ein Speicherfehler oder ein Netzwerkfehler.
  - Light-Theme: Text rgb(180,35,24) auf Hintergrund rgb(180,35,24). Der Kontrast ist 1:1, man sieht nur einen roten Fleck.
  - Dark-Theme: #ff9a93 auf #ff453a, Kontrast ≈1,7:1.
  - Nur Screenreader erhalten die Meldung (`role=alert`).
- **Abhilfe:**
  - Die globale Klasse `.error` auf Formularmeldungen begrenzen (zum Beispiel `.form-error`) und `!important` entfernen.
  - Für Toasts gilt `.toast.error { color: var(--white); }`.
- **Test:** Playwright löst in beiden Themes einen Fehler-Toast aus und prüft den Kontrast (axe oder berechnete Farben) auf mindestens 4,5:1.

#### N-02 „Lokale Daten löschen“ ist nicht abschließbar

- **Ort:**
  - `public/settings.js:197-210` und `public/auth.js:64-85`.
  - Erwarteter Text in `backend/privacy.py:159`: „LOKALE DATEN LÖSCHEN“.
- **Szenario:**
  - Der Dialog listet sauber auf, was gelöscht wird, und verlangt dann einen „Bestätigungstext“.
  - Welcher Text das ist, steht nirgends: nicht in der Meldung, nicht als Platzhalter, nicht in `aria-describedby`.
  - „Bestätigen“ ist sofort aktiv und meldet nur „Bestätigungstext stimmt nicht überein.“
  - Die Datenschutz-Löschung ist damit ohne Blick in den Quellcode nicht ausführbar.
  - Es gibt keinen E2E-Test für diesen Ablauf.
- **Abhilfe:**
  - Im Label „Zum Bestätigen ‚LOKALE DATEN LÖSCHEN‘ eingeben“ anzeigen und den Text per `aria-describedby` verknüpfen.
  - Den Button erst bei Übereinstimmung aktivieren und „Endgültig löschen“ nennen.
  - Im Dialog direkt „Erst Backup erstellen“ anbieten; der Text empfiehlt das bereits.
- **Test:** Playwright mit temporären Daten: Ein falscher Text wird abgelehnt, der richtige Text löscht, und die Ergebnisanzeige erscheint.

### 7.2 P2

#### N-03 Destruktive Buttons sehen harmlos aus

- **Ort:**
  - `.danger-button` (`public/styles.css:807-808`) wird vom später definierten `.secondary-button` (`:1045-1057`) bei gleicher Spezifität überschrieben.
  - Betroffen sind `public/index.html:290-291,341,353,369,381`.
- **Szenario:** In beiden Themes sehen diese Buttons genauso aus wie „Daten exportieren“ oder „Logs aktualisieren“:
  - „Lokale Daten löschen“
  - „Backup wiederherstellen“
  - „Logs löschen“
  - „Diagnose löschen“
  - „Lokale Daten neu laden“ (Intervals.icu und Garmin)
- **Abhilfe:** Den Selektor auf `.secondary-button.danger-button` ändern oder die Regel nach `.secondary-button` setzen. Für N-04 wird dieselbe Klasse gebraucht.

#### N-04 Coach-Aktionskarte: Hauptaktion ungestylt und nicht im Blick

- **Ort:**
  - `public/coach.js:1063-1108`: Der Bestätigungsbutton erhält keine Klasse.
  - `public/styles.css:471-475`.
- **Szenario:**
  - Auslöser im Fixture: „E2E nutrition: confirm meal“.
  - Der Freigabe-Button („Mahlzeitvorlage speichern“, „Remote-Änderung freigeben“ …) erscheint im Browser-Standardstil: 2 px schwarzer Outset-Rahmen, keine Rundung, normales Gewicht.
  - „Nicht freigeben“ ist dagegen gestylt. Die visuelle Hierarchie ist dadurch umgekehrt.
  - Die Karte erscheint unterhalb von Composer und Navigation. Sichtbar ist nur der „↓“-Sprungbutton, die Assistentenantwort verweist aber auf die Karte.
- **Abhilfe:**
  - Primärstil für die Freigabe, bei Lösch- und Remote-Aktionen `danger-button` (nach N-03).
  - Die Karte beim Erscheinen in den sichtbaren Bereich scrollen, ohne den Fokus aus dem Composer zu nehmen, und per Live-Region ansagen.

#### N-05 Nach der Freigabe springt die App in einen anderen Tab

- **Ort:** `executeCoachActionProposal` in `public/coach.js` und `#coachReceipts`.
- **Szenario:**
  - Nach „Mahlzeitvorlage speichern“ wechselt die App von `#coach` nach `#nutrition/meals`.
  - Die Quittung („Mahlzeitvorlage gespeichert · Erledigt · Nur lokal gespeichert …“) bleibt in `#coachReceipts` verborgen; nur ein Toast erscheint.
  - Wer im Gespräch weitermachen will, muss zurücknavigieren.
- **Abhilfe:** Im Chat bleiben und die Quittung inline mit „Ansehen“-Link zeigen (siehe V19).

#### N-06 Undo: doppelte Rückfrage ohne Vorschau, Objekte namenlos

- **Ort:** `public/diagnostics.js:1-6,26,64-75`.
- **Szenario:**
  - „Änderung zurücknehmen“ öffnet zwei Bestätigungsdialoge nacheinander.
  - Die Undo-Vorschau (`/api/change-history/undo/preview`) wird zwar geladen, aber nie angezeigt. Der zweite Dialog („Undo-Vorschau bestätigen?“) bestätigt etwas Unsichtbares.
  - Keiner der beiden Dialoge nennt das Objekt.
  - `planned_unit` fehlt in `CHANGE_HISTORY_LABELS`, obwohl `backend/change_history.py:16-22` den Typ aufzeichnet.
  - In der Demo heißen deshalb 10 von 25 Einträgen „Lokales Objekt erstellt“, ohne Namen oder Datum.
  - Die Historie liegt unter „Daten & Datenschutz“ und muss erst per „Historie laden“ geholt werden.
- **Abhilfe:**
  - Ein einziger Dialog mit der Vorschau in Klartext, zum Beispiel „Geplante Einheit ‚Szenario Kraft Rumpf‘ am 07.10. wird gelöscht“.
  - Eine vollständige Label-Map und den Objektnamen in jeder Zeile.
  - Ergänzt die P3-Zeile „rohe Feldnamen“ in Abschnitt 1.

#### N-07 Toasts: 3 s für alles, halbe Breite

- **Ort:** `public/shared.js:203-204` und `public/styles.css:1112`.
- **Szenario:**
  - Auch Fehlermeldungen verschwinden nach 3 s.
  - Wegen `pointer-events: none` lässt sich ein Toast weder antippen noch festhalten.
  - `left: 50%` begrenzt die Shrink-to-fit-Breite auf die halbe Viewport-Breite (188 px bei 390 px). Längere Meldungen werden so zu einer 4- bis 6-zeiligen Pille mit `border-radius: 999px`.
- **Abhilfe:**
  - Fehler bleiben stehen, bis sie geschlossen werden (Schließen-Button), oder mindestens 8 s.
  - Positionierung mit `inset-inline: 16px; margin-inline: auto; width: fit-content`.
  - Bei mehrzeiligem Text ein Radius von etwa 16 px.

#### N-08 Start lädt Analysedaten mehrfach, auch im Coach-Tab

- **Ort:**
  - `public/performance-view.js:253-260`: `renderPerformance()` startet bei jedem State-Render `renderTrainingRecords()` und `loadAnalysisReports()`.
  - `public/state-loader.js:19`.
- **Szenario:** Ein Reload auf `#coach` erzeugt in 6 s 23 API-Requests:
  - `/api/performance` (≈358 KB) zweimal.
  - `/api/analysis/endurance`, `/power-profiles` und `/training-records` je dreimal.
  - `/api/bootstrap` und `/api/chat/history` je zweimal; der zweite Bootstrap kommt nach ≈1,6 s, vermutlich durch ein Statusereignis nach den Start-Syncs (nicht verifiziert).
  - Zusammen sind das über 1 MB, bevor die erste Frage gestellt ist. Danach bleibt es bis auf P2-18 ruhig.
- **Abhilfe:**
  - Analyseberichte nur bei aktiver Analyse- oder Ausrüstungsroute laden (`ensureRouteData`).
  - Laufende Requests deduplizieren und das Ergebnis pro Inhaltsversion cachen.
- **Test:** Playwright zählt die Requests beim Start auf `#coach`.

### 7.3 P3

| Bereich | Befund | Ort | Abhilfe |
| --- | --- | --- | --- |
| Coach-Aktionskarte | Diff ohne Einheiten („Fixture breakfast · 400 · 60 · 12 · 8“) und mit technischen Werten (`ID:`, Scope, Units, „Syncjob <id> eingereiht“). | `public/coach.js:1046-1061,1166-1167` | „400 kcal · 60 g KH · 12 g E · 8 g F“, IDs nur in Details |
| Coach-Aktionskarte | Der Titel „Aktion prüfen“ ist generisch; „Freigabe und Ergebnis getrennt prüfen“ ist Jargon; die Assistentenantwort sagt „lokale Änderung“; „Garmin-Duplikat löschen“ nennt für `delete_duplicate_intervals_activity` nicht das Zielsystem. | `public/coach.js:1103,1127-1136` | Titel mit Objekt („Mahlzeitvorlage ‚…‘ speichern?“), Zielsystem nennen („Duplikat in Intervals.icu löschen“) |
| Kalender | Bei 150 % Schriftgröße (Android-Textskalierung) bricht der Kartenkopf mitten im Wort („Radfahre / n · 08:00“). | `public/styles.css:860` (`overflow-wrap: anywhere`, Spalte ≈74 px) | `hyphens: auto` (`lang="de"` ist gesetzt) und `overflow-wrap: break-word` oder Uhrzeit in eigener Zeile |
| Kalender | Eine aufgeklappte Aktivität nennt denselben Wert dreifach: „Belastung 30“, „Load 30 · RPE offen“ und „Trainingsload 30“; Dauer und Distanz wiederholen den Kopf. | `public/plan-views.js:372,377` | ein Begriff („Belastung“), Dubletten entfernen |
| Kalender | Eine aufgeklappte geplante Einheit zeigt die Workout-Rohsyntax („- 15m Z2 Pace“, „3x“) und keine Aktion. | Kalenderkarte | siehe V20 |
| Ernährung | Der Aufklapper „Aktiv- und Ruheenergie anzeigen“ ist nur 21 px hoch. | `public/nutrition.js:241` | Mindesthöhe 44 px |

### 7.4 Geprüft ohne Befund

- **Querformat (844×390):** Seitenleiste und Composer passen, kein Überlauf.
- **Schriftgröße 150 %:** kein horizontaler Überlauf in Coach, Kalender, Ernährung, Analyse und Mehr (CSS fast durchgehend in `rem`).
- **Fokus beim Tabwechsel:** Das Panel erhält den Fokus. Ein sichtbarer Fokusrahmen erscheint nur bei Tastatur und Skript-Klicks, nicht bei Touch.
- **Zurück-Taste:** Die Aktivitätsdetails haben einen eigenen History-Eintrag. Der Barcode-Dialog stoppt die Kamera beim Schließen und beim Routenwechsel.
- **Kalender:** Erneutes Tippen auf „Kalender“ springt zurück zu heute.
- **Toast-Position:** oberhalb der Navigation. Im Coach-Tab überdeckt ein mehrzeiliger Toast allerdings den Composer (siehe 8.7).
- **Nachrichtenaktionen:** „Kopieren“ und „Als Entwurf bearbeiten“ haben 44 px Trefferfläche.

### 7.5 Weitere Vorschläge

| # | Vorschlag | Nutzen | Hinweise zum Vertrag |
| --- | --- | --- | --- |
| V17 | **Kontextuelle Schnellaktionen im Coach**, dauerhaft erreichbar statt nur nach 6 h Inaktivität (`public/shared.js:2,170-173`): nach neuer Aktivität „Einheit analysieren“, am Wettkampftag „Briefing“, bei Krankheits-Check-in „Plan anpassen?“, sonst „Check-in“. Vorlagen ohne fest verdrahtete Intervals-Aktualisierung und Wahoo-Präferenz (`public/index.html:68-71`). | Häufige Anliegen mit einem Tipp; Funktionen werden auffindbar | Erzeugt nur einen Chat-Entwurf; „aktuelle Daten“ laufen weiter über den vorhandenen Sync-Pfad |
| V18 | **Chat mit Datumstrennern, Zeitstempeln und Suche.** Das Backend kann bereits suchen (`backend/http_api/chat_page.py:30-66`, `search` bis 200 Zeichen, Cursor-Paging), `created_at` ist vorhanden. | Alte Empfehlungen wiederfinden („Was sagte der Coach zur Taper-Woche?“) | Nur lesend; keine neue Persistenz |
| V19 | **Inline-Quittung mit „Rückgängig“** nach jeder freigegebenen lokalen Änderung (Coach-Karte und Toast), über den vorhandenen Undo-Pfad für die Typen aus `ENTITY_TYPES` | Fehler sofort korrigierbar; Undo wird auffindbar statt unter Datenschutz versteckt (N-05, N-06) | Undo bleibt lokal; Remote-Änderungen weiter nur über die Freigabe |
| V20 | **Aktionen an geplanten Einheiten:** „Mit Coach anpassen“ (Entwurf mit Einheitskontext wie bei Produkt → „Verwenden“), „Verschieben“ und „Ausfallen lassen“ über das vorhandene `/api/planning/commands` mit Vorschau und Freigabe. Die Schritte lesbar darstellen („3× 8 min Schwelle (Z4) · 3 min Trab“, Zielpace aus den Profilschwellen). | Die häufigste Kalenderhandlung braucht keinen Freitext-Prompt mehr; Rohsyntax verschwindet | Lokale Library-Änderung erst nach Freigabe; keine Remote-Writes, kein stilles Verschieben |
| V21 | **„Eintragen“ für gespeicherte Mahlzeiten** über denselben Coach-Entwurf wie bei Produkten (`public/nutrition.js:560-575`) | Das Standardfrühstück mit zwei Tipps erfassen; „Meine Mahlzeiten“ hat heute keine einzige Aktion | Bleibt eine explizite Coach-Anfrage (Kommentar `public/nutrition.js:1`) |

### 7.6 Ergänzung zum PR-Schnitt

| Reihenfolge | PR-Titel | Inhalt | Nachweis |
| --- | --- | --- | --- |
| 17 | `fix(ui): readable error toasts and destructive button styling` | N-01, N-03, N-07 | Playwright mit Kontrastprüfung in beiden Themes |
| 18 | `fix(privacy): show the required deletion confirmation text` | N-02 | Playwright für den Löschablauf mit temporären Daten |
| 19 | `fix(coach): action card hierarchy, visibility and inline receipt` | N-04, N-05, P3 Aktionskarte, V19 | `e2e/nutrition.spec.js` erweitern |
| 20 | `fix(history): single undo preview with object names` | N-06 | Node-Test für die Label-Map, Playwright-Undo |
| 21 | `perf(ui): load analysis reports on demand` | N-08 | Request-Zählung im Playwright-Test |
| 22 | `feat(coach): contextual quick actions, chat dates and search` | V17, V18 | Playwright mobile und desktop |
| 23 | `feat(plan): planned-unit actions and readable workout steps` | V20, P3 Kalender | Unit-Tests der Schrittformatierung, Playwright mit Freigabe |
| 24 | `feat(nutrition): log saved meals via coach draft` | V21 | Playwright |

Auch hier gilt für jedes Frontend-PR: Asset-Querys und Service-Worker-Cache bumpen.

---

## 8. Nachtrag: dritte Runde – Coach-Eingabe, Scrollen und Sprung-Button

Gleiche Umgebung wie oben (Demo-Container, iPhone 12 Pro 390×844, Light- und Dark-Theme), zusätzlich Desktop 1280×800. Für langsame Coach-Antworten wurde `/api/chat/stream` im Browser per umgeleitetem `fetch` verzögert und danach wiederhergestellt. Aufgenommen ist nur, was gemessen oder im Code eindeutig belegt wurde. Bereits erfasst und hier nicht wiederholt: P2-14 (Composer bei 320 px), N-04 (Aktionskarte hinter dem Composer), N-07 (Toasts), V17–V19.

### 8.1 P1

#### C-01 „↓“ und der Scroll nach dem Senden verfehlen den neuesten Inhalt

- **Ort:**
  - `public/coach.js:1474-1498` (`scrollChatToLatest`): Scrollziel ist die letzte `.message[data-message-id]`.
  - Keine ID haben die optimistische eigene Nachricht (`requestCoachResponse`, `:450`), wartende Nachrichten (`createPendingMessage`, `:1208`), der Streaming-Knoten und „Coach arbeitet…“ (`renderMessages`, `:1414-1418`).
- **Szenario:**
  - Nach dem Senden liegt die eigene Nachricht bei y 646–749 hinter dem Composer (646–758), „Coach arbeitet…“ bei 761–793 hinter der Navigation (ab 770). Sichtbar ist nur die vorige Coach-Antwort; ob die Nachricht abgeschickt wurde, ist nicht zu erkennen.
  - Mit zwei wartenden Nachrichten bewirkt „↓“ nichts: scrollY bleibt bei 2626 (Maximum 2975), vier Knoten bleiben verdeckt, der Button bleibt sichtbar und fokussiert nur das Eingabefeld (siehe C-02).
- **Abhilfe:**
  - Scrollziel ist das letzte Element in `#messages` (Arbeitsanzeige, Streaming-Knoten oder wartende Nachricht), nicht die letzte gespeicherte Nachricht.
  - Nach dem Scrollen `chatIsNearBottom()` erneut prüfen; der Button verschwindet erst, wenn das Ende tatsächlich sichtbar ist.
- **Test:** Playwright mit per Route verzögertem `/api/chat/stream`. Nach dem Senden und nach „↓“ liegen eigene Nachricht, wartende Nachrichten und Arbeitsanzeige vollständig oberhalb des Composers.

#### C-02 „↓“ öffnet auf dem Handy die Tastatur

- **Ort:** `public/coach.js:987-995` (`jumpToChatComposer` ruft `input.focus()` auf) und `:1744`; ebenso nach der Dateiauswahl (`:1725`).
- **Szenario:**
  - Nach dem Tippen auf „↓“ ist `document.activeElement` das Eingabefeld. Auf Touch-Geräten öffnet sich die Tastatur und verdeckt die Hälfte der Nachrichten, die man gerade sehen wollte.
  - Der Button heißt „Zu den neuesten Nachrichten springen“, verhält sich aber wie „Zum Eingabefeld“.
  - Erneutes Tippen auf den Tab „Coach“ springt dagegen korrekt ans Ende, ohne zu fokussieren.
  - Nach der Auswahl eines Anhangs öffnet sich die Tastatur ebenfalls.
- **Abhilfe:** Den Fokus nur setzen, wenn `shouldRestoreChatInputFocus()` (`public/shared.js:47`, feiner Zeiger) wahr ist. Die Funktion in `jumpToLatestMessages` umbenennen und Scrollen und Fokus getrennt halten.
- **Test:** Playwright-Projekt mit `hasTouch: true` und `isMobile: true`: Nach „↓“ ist `activeElement` nicht `#messageInput`. Im Desktop-Projekt bleibt der Fokus erhalten.

### 8.2 P2

#### C-03 Eine fertige Antwort reißt die Leseposition weg

- **Ort:** `public/coach.js:392` (`if (completed) scrollChatToResponseStart();`) und `:1445-1472`.
- **Szenario:** Während der Coach arbeitet, scrollt man nach oben (scrollY 500), um eine ältere Empfehlung nachzulesen. Sobald die Antwort fertig ist, springt die Seite auf 2609, egal wo man gerade liest.
- **Abhilfe:**
  - Nur springen, wenn man beim Senden unten war und seitdem nicht selbst gescrollt hat: beim Senden ein Flag setzen, beim ersten Nutzer-Scroll löschen.
  - Sonst bleibt die Position, und der Sprung-Button zeigt „Neue Antwort“ (V23).
- **Test:** Playwright: senden, nach oben scrollen, Antwort abschließen lassen. scrollY bleibt gleich, der Sprung-Button ist sichtbar.

#### C-04 Der Composer springt am Seitenende 34 px nach oben, Inhalt scheint durch

- **Ort:** `public/styles.css:224` (`.shell` mit 32 px Innenabstand unten), `:1154` (`#chatPanel` mit 88 px) und `:1155` (Sticky-Abstand 74 px + 12 px = 86 px).
- **Szenario:**
  - Beim Lesen sitzt der Composer 12 px über der Navigation (Unterkante bei 758).
  - Am Seitenende steht er bei 724; der Abstand zur Navigation wächst auf 46 px, und der Composer springt beim Scrollen sichtbar. Das ist der Normalzustand nach jedem Senden und bei jeder Eingabe, weil der Input-Handler (`public/coach.js:1756-1767`) ans Dokumentende scrollt.
  - Im 12-px-Spalt und unter der Navigation läuft Nachrichtentext durch, am Desktop auch unterhalb des Composers.
- **Abhilfe:**
  - Den Innenabstand von Panel und Shell an den Sticky-Abstand koppeln, zum Beispiel über eine gemeinsame Variable `--composer-offset`.
  - Hinter Composer und Navigation einen deckenden Hintergrund oder Verlauf in `--bg` legen.
- **Test:** Playwright misst die Composer-Unterkante bei scrollY 0, in der Mitte und am Maximum; die Werte sind gleich.

#### C-05 Uneinheitliche Bedienelemente, zu schmales Eingabefeld

- **Ort:** `public/styles.css:539-553,592-603,605-639,665-677,1077,1176-1179`.
- **Szenario:**
  - „+“ (Anhang): Im Light-Theme weiß auf rgb(244,244,244) mit grünem Schatten und damit praktisch unsichtbar. Im Dark-Theme akzentgrün gefüllt und damit der auffälligste Button, auffälliger als „Senden“. Ursache: `.composer button` überschreibt die Farben von `.secondary-button`, `.attachment-button` setzt keine eigenen.
  - Drei Formen nebeneinander: „+“ als randloser Kreis, das Mikrofon als umrandetes abgerundetes Quadrat (Radius 15), „Senden“ als Kreis.
  - Das Eingabefeld erhält 176 von 351 px, etwa drei Wörter pro Zeile. Bei 330 Zeichen wächst der Composer auf 166 px, zeigt nur sechs Zeilen und einen nativen Scrollbalken.
  - Die Buttons sind vertikal zentriert. Bei mehrzeiligem Text rutschen sie in die Mitte statt an die Unterkante.
  - Während einer Antwort wechselt das Layout unter 559 px auf zwei Zeilen (+50 px), der Composer springt.
  - `textarea:focus` (`:1077`) zeichnet einen Kasten mit 3-px-Ring innerhalb der Pille statt eines Rings um den ganzen Composer.
- **Abhilfe:** siehe Zielbild in 8.3. Ergänzt P2-14.

#### C-06 Enter sendet auch auf dem Handy

- **Ort:** `public/coach.js:1769-1774`; `public/index.html:77` hat kein `enterkeyhint`.
- **Szenario:** Touch-Tastaturen haben keine Umschalt-Enter-Kombination. Zeilenumbrüche sind in Nachrichten unmöglich, und ein versehentliches Enter sendet einen halben Gedanken. Die Tastatur zeigt „↵“, obwohl die Taste sendet.
- **Abhilfe:**
  - Bei `hasTouchFirstInput()` fügt Enter einen Zeilenumbruch ein (`enterkeyhint="enter"`); gesendet wird über den Button.
  - Am Desktop bleibt der bestehende Vertrag: Enter sendet, Shift+Enter bricht um, `enterkeyhint="send"`.
  - Die Änderung auf Touch ist eine bewusste Produktentscheidung; README und Tests entsprechend anpassen.
- **Test:** Node-Test für die Tastenentscheidung, Playwright mit Touch-Projekt und Desktop.

#### C-07 Warteschlange und „Steuern“ sind unverständlich

- **Ort:** `public/coach.js:197-215` (`queueChatMessage`; „steer“ führt nur `unshift` aus), `:556-563`, `:684-688`, `:1208-1213`; `public/styles.css:531` (`.pending-label` ist definiert, aber ungenutzt) und `:604`.
- **Szenario:**
  - „Steuern“ klingt, als beeinflusse es die laufende Antwort. Tatsächlich stellt es die Nachricht nur clientseitig an den Anfang der Warteschlange; das Backend erfährt davon nichts.
  - Wartende Nachrichten sehen aus wie gesendete: kein Hinweis „wartet“, kein Entfernen, kein Bearbeiten.
  - Ein deaktiviertes „Steuern“ erklärt nicht, warum es deaktiviert ist.
  - Der Platzhalter bleibt „Frage deinen Coach…“. Das Mikrofon ist während einer Antwort ausgeblendet, eine Folgefrage lässt sich nicht diktieren.
  - Die Warteschlange liegt nur im Speicher. Ein Reload oder das Beenden der PWA verwirft sie ohne Hinweis.
- **Abhilfe:**
  - Wartende Blasen mit „Wird nach der aktuellen Antwort gesendet“ beziehungsweise „Als Nächstes“ kennzeichnen und „Bearbeiten“ (zurück in den Entwurf) und „Entfernen“ anbieten.
  - „Steuern“ in „Als Nächstes senden“ umbenennen und mit einer Beschreibung versehen.
  - Platzhalter während einer Antwort: „Folgefrage – wird danach gesendet“. Das Mikrofon bleibt sichtbar.
  - Bei nicht leerer Warteschlange vor dem Verlassen warnen, wie bei `hasUnsavedChanges`.
- **Test:** Playwright mit verzögertem Stream: Kennzeichnung, Reihenfolge, Entfernen und Bearbeiten.

#### C-08 „Weitere Nachrichten laden“ verliert die Leseposition

- **Ort:** `public/coach.js:1254-1285` und `renderMessages(..., false, true)` mit `replaceChildren` (`:1399`); `public/styles.css:456` (`overflow-anchor: none`).
- **Szenario:** Nach dem Laden bleibt scrollY bei 0. Die zuvor erste Nachricht liegt jetzt bei 3489 px; man steht ohne Orientierung am Anfang von 100 älteren Nachrichten. Der Fokus fällt auf `BODY`, Screenreader verlieren den Kontext.
- **Abhilfe:**
  - Vor dem Rendern den Abstand der bisher ersten Nachricht zum Viewport merken und danach wiederherstellen.
  - Den Fokus auf diese Nachricht oder eine Statuszeile setzen („100 ältere Nachrichten geladen“).
  - Optional automatisch nachladen (V24).
- **Test:** Playwright: Die Ankernachricht steht vor und nach dem Laden an derselben Position (±2 px).

#### C-09 Chat zu luftig, Nutzerblasen zu breit

- **Ort:** `public/coach.js:1322-1370`; `public/styles.css:486,532`.
- **Szenario:**
  - Die Aktionszeilen („Kopieren“, „Als Entwurf bearbeiten“; 44 px plus 8 px Abstand) belegen bei 24 Nachrichten 1248 von 3722 px, also 34 % der Chathöhe.
  - Nutzerblasen dürfen `min(100%, 760px)` breit werden. Lange eigene Nachrichten füllen die volle Breite und sind kaum von Coach-Text zu unterscheiden.
- **Abhilfe:**
  - Aktionen als kompakte Icon-Buttons (Trefferfläche weiter 44 px, sichtbar etwa 28 px) oder nur an der letzten Nachricht und nach Antippen einer Nachricht.
  - Nutzerblasen auf etwa 85 % der Breite begrenzen.

#### C-10 Der Sprung-Button ist transparent

- **Ort:** `public/styles.css:640-664` (`background: transparent`, auch bei Hover).
- **Szenario:** Der Button ist nur ein grüner Ring. Der Pfeil liegt über Nachrichtentext (Dark-Theme: über „Beine“; Desktop: über einer Nutzerblase) und ist schwer zu erkennen und zu treffen.
- **Abhilfe:** Deckender Hintergrund in Composer-Farbe mit Schatten; optional ein Zähler für neue Inhalte (V23).

#### C-11 Anhang-Chips entfernen sich bei jedem Tipp

- **Ort:** `renderChatAttachments` (`public/coach.js:1670`) und der Change-Handler `:1714-1727`.
- **Szenario:**
  - Die Chips sind vollflächige akzentgrüne Buttons; ein Tipp irgendwo auf den Chip entfernt die Datei.
  - Lange Dateinamen brechen zweizeilig und zentriert um. Dateityp und Größe fehlen, und jeder Chip belegt eine eigene Zeile.
  - Nach der Auswahl öffnet sich die Tastatur (C-02).
- **Abhilfe:** Neutrale Chips mit Dateisymbol, gekürztem Namen (Ellipse), Typ und Größe, dazu ein eigener „×“-Button mit 44 px Trefferfläche. Die Chips stehen in einer horizontal scrollbaren Reihe.

### 8.3 Zielbild für den Composer

1. **Immer zwei Zeilen:** oben das Eingabefeld über die volle Breite, unten die Aktionszeile. Das Feld wächst bis etwa 40 % der sichtbaren Höhe und scrollt danach ohne nativen Balken. Im Busy-Zustand wechselt das Layout nicht.
2. **Genau ein Akzent:** „Senden“ (nur aktiv, wenn Text oder Anhang vorhanden ist) beziehungsweise „Stopp“. „+“ und Mikrofon sind neutrale Icon-Buttons in derselben Form (Kreis, 44 px), links in der Aktionszeile.
3. **Fokus** als Ring um den ganzen Composer (`.composer:focus-within`), kein innerer Kasten.
4. **Buttons** an der Unterkante ausgerichtet, auch bei mehrzeiligem Text.
5. **Stabile Position:** gleicher Sticky-Abstand auf der ganzen Seite, deckender Hintergrund dahinter (C-04).
6. **Enter** abhängig vom Eingabegerät, mit passendem `enterkeyhint` (C-06).
7. **Busy-Zustand:** Der Platzhalter erklärt die Warteschlange. „Stopp“ und „Als Nächstes senden“ sind klar getrennt, das Mikrofon bleibt verfügbar (C-07).
8. **Anhänge** als kompakte Chip-Reihe über dem Eingabefeld (C-11).
9. **Sprung-Button** deckend über dem Composer, mit Hinweis auf neue Inhalte, ohne Fokus auf Touch-Geräten (C-01, C-02, C-10).
10. **Tastatur offen:** Composer direkt über der Tastatur, Navigation ausgeblendet. Das ist mit `chat-keyboard-open` angelegt, hier aber nicht prüfbar (siehe 8.4).
11. **Entwurf** übersteht Reload und Navigation in derselben Browsersitzung; das Schließen der PWA verwirft ihn (V22).

### 8.4 Geprüft ohne Befund und Grenzen

- **Tabwechsel:** Die Chat-Scrollposition bleibt erhalten (900 → 900).
- **Erneutes Tippen auf „Coach“:** springt ans Ende, ohne die Tastatur zu öffnen.
- **„↓“ ohne wartende Inhalte:** Die letzte Nachricht landet 12 px über dem Composer.
- **Nachrichtenaktionen:** 44 px Trefferfläche, ausreichender Kontrast.
- **Desktop 1280×800:** Composer 760 px breit, Eingabefeld 585 px, sonst passend; betroffen sind nur C-04 (Durchscheinen), C-05 („+“) und C-10.
- **Grenze Touch:** Das Preview emuliert kein Touch (`maxTouchPoints` 0, kein grober Zeiger). Das Layout bei offener Tastatur (`chat-keyboard-open`, `visualViewport`) ist nur statisch geprüft und muss im Playwright-Projekt `mobile` (Touch über `devices["Pixel 5"]`) oder auf einem echten Gerät nachgeprüft werden.
- **Grenze Streaming:** Der Fixture-Coach antwortet ohne Text-Deltas. Live-Streaming und das Scrollverhalten während des Streams sind ungeprüft. Empfehlung: einen Fixture-Trigger mit verzögerten Deltas ergänzen, zum Beispiel „E2E fixture: slow stream“.

### 8.5 Weitere Vorschläge

| # | Vorschlag | Nutzen | Hinweise zum Vertrag |
| --- | --- | --- | --- |
| V22 | **Entwurf sichern:** Text und Warteschlange in `sessionStorage` halten (wie `coachPendingTurn`, `public/coach.js:1240`); nach dem Senden löschen. Ein Reload oder die Navigation innerhalb derselben Browsersitzung behält sie. Das Schließen der PWA verwirft sie bewusst (konsistent mit Audit-Finding F06 aus #439: keine persistente Textspeicherung im Browser). Explizites Abmelden löscht sie; ein Ablauf der Sitzung (401) bewahrt sie für die Wiederaufnahme nach dem Login | Ein Reload oder ein Sitzungsablauf verwirft keine halb geschriebene Nachricht mehr; heute warnt nur `beforeunload` | Athletentext liegt dann unverschlüsselt im Browser. Nur `sessionStorage`, nie `localStorage`. Anhänge werden nicht gespeichert; Einträge mit Anhang werden nie automatisch gesendet und erscheinen nach dem Neuladen nur als bearbeitbarer Entwurf mit dem Hinweis „Anhang erneut hinzufügen“. Regressionstest ist verpflichtend |
| V23 | **Sprung-Button mit Hinweis „Neue Antwort“** oder Zähler, wenn während des Lesens Inhalte hinzukommen | Man verpasst keine Antwort und wird trotzdem nicht weggescrollt (C-03) | Rein clientseitig |
| V24 | **Älteres automatisch nachladen**, sobald der Chat-Anfang sichtbar wird (IntersectionObserver), mit Positionserhalt aus C-08 | Durchgehendes Scrollen statt Button | Nutzt das vorhandene Cursor-Paging; der Button bleibt als Fallback für Tastatur und Screenreader |

### 8.6 Ergänzung zum PR-Schnitt

| Reihenfolge | PR-Titel | Inhalt | Nachweis |
| --- | --- | --- | --- |
| 25 | `test(e2e): delayed streaming fixture and shared browser helpers` | Fixture-Trigger mit verzögerten Deltas und gemeinsame Browser-Helfer; Grundlage für 26–31. Kein neues Touch-Projekt nötig: `mobile` und `mobile-small` emulieren Touch bereits (`devices["Pixel 5"]`) | Neue Specs laufen gegen die Fixture |
| 26 | `fix(coach): scroll to newest content and jump without keyboard` | C-01, C-02, C-03, C-10, V23 | Playwright mit verzögertem Stream, Touch- und Desktop-Projekt |
| 27 | `fix(ui): stable sticky composer offset and backdrop` | C-04 | Playwright misst die Composer-Position an drei Scrollpunkten |
| 28 | `feat(coach): two-row composer with consistent controls and mobile Enter` | C-05, C-06, C-11, P2-14 | Playwright mobile-small bis desktop in beiden Themes; Enter und Shift+Enter am Desktop manuell |
| 29 | `feat(coach): explain and manage queued messages` | C-07 | Playwright mit verzögertem Stream |
| 30 | `fix(coach): keep reading position when loading older messages` | C-08, V24 | Playwright mit Positionsvergleich |
| 31 | `style(coach): compact message actions and bubble width` | C-09 | Playwright mobile, Messung der Chathöhe |
| 32 | `feat(coach): keep the chat draft for the browser session` | V22 | Node-Test; Playwright getrennt: Reload behält den Entwurf, 401 behält Warteschlange für die Wiederaufnahme, explizites Logout löscht beides; Eintrag mit Anhang wird nicht automatisch gesendet |

Auch hier gilt für jedes Frontend-PR: Asset-Querys und Service-Worker-Cache bumpen. Bei 28 zusätzlich Mikrofonberechtigung und Enter-Verhalten manuell prüfen.

### 8.7 Gegenprüfung auf dem Pixel 7

Alle Coach-Befunde aus Abschnitt 8 und die viewport-abhängigen Punkte der früheren Runden wurden mit dem Preset Pixel 7 (412×915 hoch, 915×412 quer) wiederholt, in Dark- und Light-Theme. Die verzögerte Antwort wurde wie oben simuliert und danach zurückgesetzt. Grenzen wie in 8.4: keine Touch-Emulation, keine Stream-Deltas.

| Befund | Ergebnis Pixel 7 | Messwerte |
| --- | --- | --- |
| C-01 | bestätigt | Nach dem Senden: eigene Nachricht 717–820 komplett hinter dem Composer (717–829), „Coach arbeitet…“ 832–864 hinter der Navigation (841–903). Mit zwei wartenden Nachrichten ändert „↓“ scrollY nicht (3139 von 3464), vier Knoten bleiben verdeckt. |
| C-02 | bestätigt | Nach einem echten Klick auf „↓“ ist `#messageInput` fokussiert; ebenso nach der Dateiauswahl. |
| C-03 | bestätigt | Leseposition 500 während der Antwort, nach Abschluss Sprung auf 3573. |
| C-04 | bestätigt | Composer-Unterkante 829 beim Lesen, 795 am Seitenende (Abstand zur Navigation 12 → 46 px); quer 400 → 380. Nutzerblasen bleiben hinter dem halbtransparenten Composer (94 % deckend, Blur) als Fläche sichtbar, unter der Navigation läuft Text durch. |
| C-05 | bestätigt | Eingabefeld 198 von 373 px. 352 Zeichen ergeben 18 Zeilen, davon 6 sichtbar mit nativem Scrollbalken; Composer 166 px hoch, Buttons mittig. Im Busy-Zustand zwei Zeilen (Composer 61 → 112 px). Light: „+“ weiß auf rgb(244,244,244), praktisch unsichtbar; Dark: „+“ akzentgrün und auffälligster Button. Innerer Fokuskasten sichtbar. |
| C-06 | bestätigt (Code und Ereignis) | Enter löst `submit` aus; `enterkeyhint` fehlt. |
| C-07 | bestätigt | Keine `.pending-label`, Platzhalter unverändert, Mikrofon `display: none`. „Steuern“ stellt die Nachricht vor die zuvor eingereihte. |
| C-08 | bestätigt | Ankernachricht 279 → 3423 px, scrollY bleibt 0, Fokus auf `BODY`. |
| C-09 | bestätigt | Aktionszeilen 1560 von 4299 px (36 %) bei 30 Nachrichten; breiteste Nutzerblase 373 px = volle Breite. |
| C-10 | bestätigt | Hintergrund `rgba(0,0,0,0)`; im Light-Theme liegt der Pfeil über „Beine“. |
| C-11 | bestätigt | Langer Dateiname: Chip 351×56 px, zweizeilig; zweiter Chip in eigener Zeile; Composer wächst auf 176 px; ganzer Chip entfernt die Datei. |
| N-01 | bestätigt | Fehler-Toast im Light-Theme Text und Hintergrund rgb(180,35,24). |
| N-04 | bestätigt | Aktionskarte 738–994 bei 915 px Höhe, größtenteils hinter Composer und Navigation; „Mahlzeitvorlage speichern“ mit 2-px-Outset-Rahmen und Radius 0. |
| N-07 | bestätigt, ergänzt | Toast 199 px breit und 90 px hoch (vier Zeilen). Im Coach-Tab liegt er bei 723–813 über Composer und „↓“-Button. Er blockiert keine Tipps (`pointer-events: none`), verdeckt aber für 3 s Eingabe, „+“ und Sprung-Button. |
| Übrige Tabs | ohne neuen Befund | Kalender, Analyse, Ernährung und Mehr ohne horizontalen Überlauf. Kleine Ziele nur die bekannten: Info-Buttons und FTP/eFTP 29 px (P2-16), Energie-Aufklapper 21 px (7.3). |
| Querformat | ohne neuen Befund | Seitenleiste statt Navigation, Composer 748 px breit, Eingabefeld 573 px; nur C-04 (20 px) und C-05 („+“) sichtbar. |

Ergänzung zu N-07: Toasts im Coach-Tab oberhalb des Composers positionieren (zum Beispiel über `--composer-offset` aus C-04) oder oben anzeigen. Das gehört zu PR 17.

---

## 9. Umsetzung: Reihenfolge und Entscheidungen

Bestätigte Entscheidungen (09.10.2026):

1. **Enter auf Touch-Geräten (C-06):** Auf Touch-first-Geräten fügt Enter einen Zeilenumbruch ein; gesendet wird über den Button. Am Desktop bleibt Enter = Senden und Shift+Enter = Zeilenumbruch.
2. **Asset-Versionen in Tests:** Die festen Versionsliterale in `tests/test_server_frontend.py` werden durch eine Konsistenzprüfung ersetzt (`?v=` in `public/index.html` gleich `ASSETS` in `public/service-worker.js`).
3. **Größere Features** (V5, V6, V7, V9-Outbox) werden erst nach den Phasen 0–3 neu priorisiert. Offline wird vorerst nur ehrlich beschriftet (PR 11).

Reihenfolge:

| Phase | Inhalt | PRs |
| --- | --- | --- |
| 0 | Grundlagen: idempotenter Fixture-Seed (P2-20), verzögerter Stream-Trigger und gemeinsame Browser-Helfer, Seed-Version 6 | 15, 25 |
| 1 | P1-Fehler | 1, 2, 3, 18, 27, 17, 26, 4 |
| 2 | Coach: Composer, Warteschlange, Entwurf, Verlauf, Aktionskarten | 28, 29, 32, 30, 31, 20, 19, 13 sowie Live-Regionen und Markdown-Tabellen |
| 3 | Daten- und Darstellungskorrektheit | 7, 8, 21, 6, 5, 9, 11, 14, 10 |
| 4 | Features | 22, 23, 24, V4, V3, V5–V7 |
| 5 | P3-Feinschliff | 16 in kleinen Paketen |

Zusammengelegt: PR 12 (P2-14) geht in PR 28 auf; der Chat-Teil von PR 11 (P2-12, V10) in PR 29 und 32. Die Playwright-Projekte `mobile` und `mobile-small` emulieren Touch bereits (`devices["Pixel 5"]`); PR 25 beschränkt sich deshalb auf den Stream-Trigger und die Helfer.
