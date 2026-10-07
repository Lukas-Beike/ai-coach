# Umsetzungsplan für Trainingsanalysen und neue Funktionen

Stand: 7. Oktober 2026. Grundlage ist Commit `db23598d` plus nicht committete lokale Arbeit. Status: Pakete 1 bis 5, 7, 11 und 12 weitgehend lokal umgesetzt; Pakete 6, 8, 9 und 10 haben Backend/API, aber noch keine Oberfläche beziehungsweise Coach-Anbindung.

Der Plan ergänzt Intervals Coach um nachvollziehbare Trainingsanalysen, persönliche Erholung, Wettkampfvorbereitung und praktische Trainingsfunktionen. Neu aufgenommen sind der Analyse-Tab **Body**, die verlässliche Auswertung beider Kalender-Flags **`[NO_TRAINING]` und `[NO_INTENSITY]`** sowie der Garmin-Tagesverbrauch im Ernährungstagebuch. Die nächste Lieferung behebt zuerst die Kalenderregeln und ergänzt danach Body und Tagesenergie. Bestehende Pakete für Kalenderdetails, Wochenrückblick, Intervallqualität, Ausdauerentwicklung, Erholung, Leistungsprofile, Planungsszenarien, Verpflegung, Einflussanalysen und Ausrüstung werden gezielt erweitert.

Die ursprünglichen Paketnummern bleiben als Referenzen erhalten. Einige ihrer Abläufe sind inzwischen vorhanden; vor jeder Umsetzung ist die konkrete Lücke zum aktuellen Code zu bestimmen. Neu geplante Erweiterungen werden ausdrücklich beschrieben und bauen auf vorhandenen Modulen auf.

Jedes Arbeitspaket liefert einen nutzbaren Ablauf mit Backend, HTTP/API, Coach-Anbindung, Oberfläche und passenden Tests. Die Funktionen entstehen in getrennten PRs; größere Pakete werden entlang ihrer beschriebenen Teilschritte aufgeteilt. Dieser Plan beauftragt keine Veröffentlichung oder Umstellung einer bestehenden Installation.

## Geprüfte Grundlage

| Bereich | Bereits vorhanden | Konsequenz für die Umsetzung |
| --- | --- | --- |
| Analyse | SVG-Diagramme für Belastung/Form, Leistungsentwicklung und Erholung; datierte Backend-Historie, 14-Tage-/12-Wochen-Darstellung und Wochenbericht | `public/analysis.js` und `backend/performance/chart_history.py` erweitern; bestehende Diagramme und Zeitraumwahl für Body weiterverwenden |
| Kalender | Geplante und absolvierte Einheiten, konservative Paarung und Soll-Ist-Vergleich nach Belastung oder Dauer | Aktivitätsdetails aus dem Kalender öffnen; der entfernte Verlauf-Tab bleibt entfernt |
| Detaildaten | `backend/sync/activity_details.py` lädt bereits Aktivitätsdetails, Streams und Intervalle; `ActivityReadService.detail` liefert lokale Details und Cache-Verfügbarkeit | Vorhandenen gezielten Detail-Sync um Bestleistungen, Intervallstatistik und Kontext ergänzen |
| Intervals-Sync | `IntervalsSnapshotReader.fetch_snapshot` lädt Aktivitäten, Wellness, Events und Athletenwerte | Gezielte Detailabfragen über den bestehenden Sync ergänzen; Listenabrufe garantieren keine vollständigen Zeitreihen |
| Intervals-Wellness | Das `Wellness`-Schema liefert unter anderem `weight`, `bodyFat`, `kcalConsumed`, `soreness`, `fatigue`, `stress`, `injury`, `spO2`, `hydration`, `respiration`, `steps`, `carbohydrates`, `protein` und `fatTotal` | Optionale, quellengenaue Zeitreihen für Body, Energie und Erholung normalisieren; fehlende Messungen bleiben Lücken |
| Garmin | `garminconnect==0.3.17` liefert bereits Aktivitäten, Schlaf, HRV, Tagesstatus, Readiness, Ruhepuls, Rennprognosen, Max-Metriken, FTP, Laktatschwelle, Gewicht und Ausrüstung | Body Composition, Tageskalorien und historische FTP-Werte über capability-geprüfte, getrennte Abrufe ergänzen |
| Gesundheitsdaten | Garmin-/Intervals-Werte, datierte Verläufe und Durchschnittsvergleiche | Persönliche Normalbereiche, Schlafauswertungen und Quellenwechsel getrennt berechnen |
| Kalender-Constraints | `[NO_TRAINING]`, `[NO_INTENSITY]` und `[SHORT_ONLY]` werden aus iCal-Beschreibungen erkannt; relevante Termine können derzeit herausgefiltert werden | Marker aus Titel und Beschreibung zentral normalisieren und vor jeder Planänderung auswerten; ein Sperrtermin bleibt im Kontext sichtbar |
| Rückmeldungen | Aktivitätsfeedback speichert Freitext; Tages-Check-ins enthalten unter anderem Session-RPE | RPE je Aktivität strukturiert ergänzen; Tages-RPE nicht mehreren Einheiten zuordnen |
| Saison | Wettkämpfe und eine datumsbasierte Phasenzuordnung in `backend/planning/season.py` | Wettkampfeignung aus absolviertem Training getrennt von der kalendarischen Phase bewerten |
| Ernährung | Tagebuch, Mahlzeitenvorlagen, Lebensmittelberechnung und explizite Erfassung über den Coach; Garmin-Tagesstatistiken enthalten Kalorien, die Gesundheitsprojektion mittelt sie derzeit über ein Fenster | Datierten Verbrauch aus vorhandenen Tagesstatistiken verfügbar machen; optional aktive/Ruhekalorien ergänzen; keinen Durchschnitt als Tageswert darstellen |
| Dauerhafte Daten | Aktuelles SQLCipher-Schema, Backup und explizite Exportlisten | Neue Felder und Tabellen zusammen mit Schema-Prüfung, Export und Restore-Verträgen ergänzen |

## Oberfläche und Einstiegspunkte

Die Hauptnavigation bleibt `Coach`, `Geplant`, `Analyse`, `Ernährung`, `Mehr`. Neue Unterbereiche werden mit dem jeweiligen Feature eingeführt.

| Ort | Geplante Inhalte |
| --- | --- |
| Analyse → Leistung | Vorhandene Diagramme, Ausdauerentwicklung, Leistungsprofil und wiederkehrende Trainings |
| Analyse → Body | Drei Diagramme für Gewicht, KFA und W/kg; Zeiträume 14 Tage und 12 Wochen; Messzeit, Quelle und Datenlücken sichtbar |
| Analyse → Belastung | Diagramm Trainingszeit (Summe der Bewegungszeit) neben der akuten Belastung; 14 Tage täglich, 12 Wochen als Wochensumme. Ein eigener Wochen-Tab entfällt |
| Analyse → Erholung | Heutige Einordnung, persönliche Normalbereiche, Schlafverläufe und später persönliche Einflussanalyse |
| Geplant → Übersicht → absolvierte Einheit | Detailansicht mit Zusammenfassung, Diagrammen, Trainingsqualität, Vergleich und Feedback; Rückkehr zum gleichen Kalendertag |
| Geplant → Übersicht → heutiger Tag | Kompakte Erholungseinordnung mit Link auf die vollständige Auswertung |
| Geplant → Übersicht → geplante Einheit | Trainingsziel, Zielwerte, Link zu passenden früheren Einheiten und Verpflegung |
| Geplant → Saison | Wettkämpfe, Trainingsphasen, Vorbereitungsstand und Szenarienvergleich |
| Geplant → Bibliothek | Bestehende Vorlagen |
| Ernährung → Trainingsverpflegung | Auswahl einer Einheit und zeitliche Abfolge für vorher, währenddessen und danach |
| Ernährung → Tagebuch | Tageskarte mit Garmin-geschätztem Verbrauch; Gesamtwert, Aktualität sowie aktive und Ruhekalorien optional aufklappbar |
| Mehr → Athletenprofil | Ausrüstung, Verträglichkeit, Schlafziel und persönliche Vorgaben |
| Coach | Passende Schnellstarts und Verweise auf konkrete Berichte, Aktivitäten oder Wettkämpfe |

Auf kleinen Bildschirmen enthält eine Analysekarte eine Hauptaussage, wenige Kennzahlen und eine Grafik. Ausführliche Tabellen und Erklärungen werden aufgeklappt oder in einer Detailansicht geöffnet. Zeitraum und Sportfilter gelten nur für die jeweils passende Auswertung. Training und Erholung verwenden unterschiedliche Zeitfenster, wenn ihre Methoden dies benötigen.

## Gemeinsame Daten und Berechnungsregeln

Berechnungen erfolgen reproduzierbar im Backend. Der Coach bekommt begrenzte Ergebnisse mit Belegen, erklärt sie und formuliert Vorschläge. Bestehende Coach-Lesewege werden erweitert, bevor zusätzliche Tools eingeführt werden. Ein neues Tool wird nur angelegt, wenn ein bisheriger Leseweg die Verantwortung nicht sinnvoll abdecken kann.

Jede abgeleitete Kennzahl liefert Wert, Einheit, Zeitraum, Quelle, Beobachtungsdatum, Berechnungsmethode, Datenabdeckung und relevante Aktivitätsreferenzen. Unzureichende Daten liefern einen erklärten Zustand wie `insufficient_data`, statt einen geschätzten Nullwert. Abrufzeit und Messzeit bleiben getrennt. Methodische Zustände sind eine kleine gemeinsame Datenkonvention, kein allgemeines Analyse-Framework.

Metriken verwenden Zeitstempel und tatsächliche Zeitabstände. Fehlende Messungen, Pausen, Sensorausfälle und Provider-Duplikate werden explizit behandelt. Für historische Zonen und Zielbereiche gelten die Schwellen zum damaligen Zeitpunkt. Aktuelle FTP oder aktuelle Pulszonen werden nicht unbemerkt auf ältere Trainings angewendet. Fehlt die historische Grundlage, wird dies ausgewiesen.

UI-Diagramme dürfen Daten zur Darstellung verdichten. Intervallbewertung und Bestleistungen rechnen auf den geeigneten Originaldaten oder auf datierten, ausreichend genauen Provider-Ergebnissen. Die auf 2.000 Punkte begrenzte Coach-Projektion wird nicht als Grundlage für Sprintbestwerte verwendet.

Leseansichten und normale Coach-Nachrichten verwenden gespeicherte Daten. Ein fehlender Detaildatensatz wird über eine ausdrückliche Ladeaktion und einen bestehenden Sync-Job beschafft. Neue Berechnungen lösen keine dauernden Providerabrufe aus. Der Wochenrückblick lässt sich ohne AI-Aufruf anzeigen; eine Coach-Erklärung startet auf Nutzerwunsch.

Provider-Erweiterungen sind optional und fehlertolerant: Capability-Erkennung erfolgt vor dem Abruf, jeder Datenbereich hat eigenen Fehler- und Freshness-Status, und ein nicht unterstützter oder fehlgeschlagener Endpunkt verwirft keine anderen Sync-Daten. Rohdaten bleiben untrusted; Coach-Kontext erhält nur bereinigte Werte mit Quelle und Messdatum. Neue Abrufe laufen ausschließlich in den bestehenden Sync-Pfaden oder über eine ausdrückliche Aktualisierung.

Neue dauerhafte Daten werden mit dem aktuellen SQLCipher-Schema initialisiert. Schema-Erweiterungen erhalten versionierte, transaktionale Migrationen mit Upgrade-Regressionstests; unterstützte vorherige Releases können direkt aktualisiert werden. Unbekannte oder neuere Schemata werden ohne Datenänderung abgewiesen. Same-build-Restart und Restore eines Backups mit dem aktuellen Schema bleiben überprüfbare Verträge.

## Arbeitspakete und Abhängigkeiten

| Paket | Ergebnis | Benötigt | Größe |
| --- | --- | --- | --- |
| 0 | Verlässliche Kalender-Constraints für Planung und Coach | Aktueller Kalender-Sync | Mittel |
| 1 | Verlässliche Detaildaten und Aktivitätsansicht aus dem Kalender | Aktueller Stand | Groß |
| 2 | Wochenrückblick, Blockvergleich und Trainingsreiz | Paket 1; Teilbericht funktioniert auch ohne Streams | Mittel |
| 3 | Intervallqualität und strukturierter RPE je Aktivität | Paket 1 | Groß |
| 4 | Ausdauer-Effizienz, Herzfrequenzdrift und Stabilität langer Einheiten | Paket 1 | Groß |
| 5 | Erholungsbereich, Schlafdefizit und Schlafregelmäßigkeit | Vorhandene Gesundheitshistorie | Mittel |
| 5a | Gemeinsame Körperdatenbasis und Body-Tab mit Gewicht, KFA und W/kg | Intervals-Wellness, Garmin-Körperdaten, datiertes FTP | Mittel |
| 5b | Garmin-Tagesverbrauch im Ernährungstagebuch | Vorhandene Tagesstatistiken, optional Calories Daily; bestehende Ernährung | Klein |
| 6 | Leistungsprofil und Vergleich wiederkehrender Trainings | Pakete 1, 3, 4 | Groß |
| 7 | Saisonansicht und wettkampfspezifische Vorbereitung | Pakete 2, 3, 4 | Mittel |
| 8 | Plan-Simulation und Szenarienvergleich | Paket 7 und vorhandene Planvorschau | Groß |
| 9 | Trainingsverpflegung | Pakete 1, 7; bestehende Ernährung | Mittel |
| 10 | Persönliche Einflussanalyse | Paket 5 und ausreichend getaggte Tage | Mittel |
| 11 | Bewertete Intervals-/Garmin-Erweiterungen für Leistung, Aktivität und Erholung | Pakete 1, 5, 6; ausreichende Capability-Abdeckung | Groß |
| 12 | Ausrüstung, Lebensdauer und ausgemusterte Komponenten | Paket 1 und strukturierte Zuordnung | Mittel |

Die nächste Umsetzung beginnt mit **0 → 5a → 5b**, gefolgt von den gezielten Erweiterungen der bestehenden Analysepakete. Die Nummern erhalten die Referenzen des Bestandsplans. Größe bezeichnet den relativen Umfang der beschriebenen Verantwortung einschließlich Tests und UI; für bereits vorhandene Abläufe wird nur der verbleibende Erweiterungsaufwand geschätzt. Die konkrete Zeitabschätzung folgt auf die Eingrenzung je PR und auf die verfügbare Datenqualität.

## Paket 0 Kalender-Constraints (`[NO_TRAINING]` und `[NO_INTENSITY]`)

**Problem:** Beide Marker müssen verbindliche Trainingsregeln sein. `[NO_TRAINING]` wird heute beim Erkennen als `training_relevant=false` markiert und kann dadurch aus dem Planungskontext verschwinden. `[NO_INTENSITY]` wird nur in einem Teilpfad der adaptiven Vorschau berücksichtigt. Zusätzlich werden die Marker derzeit nur aus der Beschreibung gelesen. Damit kann ein Termin im Titel oder eine wiederkehrende Ausnahme übersehen werden.

**Umsetzung:** Titel und Beschreibung jedes iCal-Termins in einer zentralen, case-insensitiven Normalisierung auswerten. Die Normalisierung liefert Marker, Quelle, Terminreferenz, lokale Gültigkeit, Wiederholungsinstanz und Synchronisationszeit. Ein `[NO_TRAINING]`-Termin bleibt in Kalender-, Coach- und Planungsdaten sichtbar und sperrt Training an jedem betroffenen lokalen Tag. Ein `[NO_INTENSITY]`-Termin erlaubt ausschließlich als locker eingestufte Einheiten; unbekannte Intensität benötigt Klärung. Bei beiden Markern gilt die Trainingssperre. `[SHORT_ONLY]` bleibt eine optionale Dauergrenze mit einer ausdrücklich festgelegten Maximaldauer.

**Architektur:** `backend/providers/calendar.py` interpretiert die untrusted iCal-Eingabe. Eine fokussierte gemeinsame Prüfung unter `backend/calendar/` liefert dieselbe Entscheidung für Kalenderprojektion, Planerstellung, Bearbeitung, Verschieben, Ersetzen, adaptive Vorschau, deren Anwendung und expliziten Bibliotheks-Sync. `training_relevant` darf Sperrtermine nicht ausschließen. Verstöße gegen beide Flags blockieren die betroffene Änderung unabhängig von der Coach-Antwort. Das Anwenden prüft Kalender- und Planrevision erneut; veraltete Vorschauen müssen neu erstellt werden. Bereits vorhandene Einheiten werden als Konflikt angezeigt und erst nach ausdrücklich genehmigter Planänderung angepasst. Ein Sync-Fehler darf bekannte Sperren nicht entfernen.

**Vereinfachung:** Im Kalender sichtbare Hinweise „Training gesperrt“ und „Nur locker“ mit Quelle und letzter Synchronisation anzeigen. Eine kurze Anleitung und kopierbare Marker erklären die Nutzung im Google-Termintitel oder in der Beschreibung. Lokale Bedienfelder und Coach-Aufträge können dieselben Regeln ausdrücklich setzen; sie schreiben nicht automatisch in Google-Termine. Freitext wie „Reise“ erzeugt keine heimliche Sperre.

**Abnahme:** Marker in Titel, Beschreibung, gemischter Groß-/Kleinschreibung, wiederkehrenden und mehrtägigen Terminen werden gleich behandelt. Ein Termin mit beiden Markern bleibt blockierend. Zeitzonen und Sommer-/Winterzeit verwenden die Athletenzeitzone. Eine Vorschau, ein gespeicherter Plan und eine spätere Anwendung verwenden dieselbe Entscheidung. Tests prüfen insbesondere, dass `[NO_TRAINING]` und `[NO_INTENSITY]` weder aus dem Coach-Kontext herausfallen noch durch `training_relevant_only` verloren gehen.

## Paket 1 Detaildaten und Aktivitätsansicht

**Umsetzung:** Den bereits vorhandenen gezielten Detail-Sync und die Kalenderdetailansicht verwenden. Die öffentlich dokumentierten Ergänzungen für Best Efforts, Intervallstatistiken, Wetter, Karte und Histogramme einzeln mit synthetischen Provider-Fixtures anbinden. Der Sync kennt Aktivitäts-ID, Providerrevision beziehungsweise Inhaltsfingerprint, Messkanäle, Abdeckung und Ladezustand. Bereits aktuelle Details werden wiederverwendet; geänderte Providerdaten invalidieren betroffene Ableitungen.

**Daten und Architektur:** `backend/providers/intervals.py` besitzt den Transport; `backend/sync/activity_details.py` und der vorhandene Job-/Cache-Pfad besitzen Abruf und Speicherung. `backend/activities/read_service.py` liefert lokale Details. Neue Kanäle verwenden die vorhandene Detailpersistenz; zusätzliche Tabellen sind nur nötig, wenn Lebensdauer oder Größe dies erfordern. Requests, Antwortgröße, Punktzahl, Laufzeit und Batchumfang erhalten harte, in Tests geprüfte Grenzen. Verfügbare Kanäle werden einzeln ausgewiesen.

**Oberfläche und Coach:** Ein Button in der absolvierten Kalenderkarte öffnet die Detailansicht. Ein authentifizierter lokaler GET liefert die bereinigte Ansicht. Fehlende Details zeigen den Button „Detaildaten laden“, dessen POST mit CSRF einen Sync-Job startet. Das Öffnen allein ruft keinen Provider auf. Die Ansicht zeigt Datum, Sport, Dauer, Belastung, verfügbare Kurven und Quellen. „Mit dem Coach besprechen“ übernimmt die genaue Aktivitätsreferenz als sichtbaren Entwurf; der Nutzer sendet ihn selbst. Browser-Zurück stellt Datum, Filter und Scrollposition wieder her.

**Abnahme:** Eine Aktivität mit vollständigen, partiellen oder fehlenden Details ist verständlich bedienbar. Zwei Aufzeichnungen desselben Trainings erzeugen eine kanonische Auswertung. Ein Timeout oder Abbruch verändert weder lokale Planung noch vorhandene gültige Details. Wiederholtes Öffnen bleibt lokal. Sensorausfälle und Datenlücken sind sichtbar. Der bestehende Soll-Ist-Vergleich im Kalender bleibt erhalten.

## Paket 2 Wochenrückblick und Trainingsreiz

**Umsetzung:** Einen deterministischen Wochenbericht aus absolvierten Aktivitäten, vorhandener Paarung zu geplanten Einheiten, Check-ins und datierten Leistungswerten bauen. Er zeigt Umfang je Sport, geplante und absolvierte Belastung, zusätzliche Einheiten, Schlüsseltrainings, verfügbare Rückmeldungen und nachvollziehbare Entwicklungen. Abgeschlossene Wochen lassen sich mit der Vorwoche oder einem gewählten Trainingsblock vergleichen; die laufende Woche wird als unvollständig gekennzeichnet.

**Metriken:** Zeit in dokumentierten Intensitätsbereichen, Verteilung harter Trainingstage und Änderungen von Umfang/Belastung. Historische Zonen und Schwellen müssen bekannt sein. Für jede Zonenverteilung die auswertbare Dauer relativ zur gesamten passenden Trainingsdauer anzeigen. Krafttraining wird nicht aus einer Herzfrequenzverteilung als Ausdauerreiz klassifiziert. Eine 80/20-Verteilung ist keine feste Bewertungsvorgabe.

**Oberfläche und Coach:** Es gibt keine eigene Wochenansicht in der Oberfläche; die Trainingszeit erscheint als Diagramm unter Analyse → Belastung. Der Wochenbericht bleibt als Datenquelle für den Coach (`get_training_report`) bestehen. Der Coach kann Berichte weiterhin über seinen bestehenden Leseweg besprechen. Berechenbare Diagrammdaten werden wiederverwendet statt separat dauerhaft dupliziert.

**Owner:** `backend/performance/` für Berechnungen, `backend/activities/matching.py` und `calendar_projection.py` für Paarung, `backend/coach/` für Erklärung, `public/analysis.js` für Darstellung. Ein Wochenbericht bleibt ein begrenztes Domänenmodul.

**Abnahme:** Doppelte Aktivitäten zählen einmal. Fehlende Belastung wird nicht als null interpretiert. Ruhe, bestätigte Trainingspause und ungeklärte fehlende Einheit werden unterscheidbar. Wochen entsprechen der Athletenzeitzone. Jede Entwicklung verweist auf datierte Belege; ohne passende Daten entsteht keine erfundene Verbesserung. Das Lesen des Berichts ändert keinen Plan.

## Paket 3 Intervallqualität

**Umsetzung:** Die ausführbaren Schritte des geplanten Trainings mit vorhandenen Runden beziehungsweise passenden Zeitabschnitten vergleichen. Zuerst eindeutig gepaarte, zeitbasierte Intervalle unterstützen, danach distanzbasierte Einheiten. Automatische Erkennung auf Basis bloßer Leistungsschwankungen ist eine spätere Erweiterung; bei mehrdeutiger Paarung bleibt die Zuordnung offen.

**Metriken:** Arbeitszeit im Zielbereich, mittlere Zielabweichung je Wiederholung, absolvierte Wiederholungen und Leistungs-/Geschwindigkeitsabfall zwischen vergleichbaren frühen und späten Wiederholungen. Ein universeller Qualitätsscore ist für die erste Version nicht erforderlich. Bei Pace prozentuale Änderungen konsistent in Geschwindigkeit umrechnen oder ausdrücklich als Zeitänderung benennen.

**Dauerhafte Daten:** Strukturierter RPE 0–10 und optional ein Grund für Abbruch beziehungsweise Abweichung je Aktivität. Bestehender Feedback-Freitext bleibt erhalten. Die geplanten Ziele und ihre damalige Schwellenbasis müssen rekonstruierbar sein; spätere Bearbeitung einer Vorlage darf die ursprünglichen Ziele nicht ändern. Tags wie Krankheit oder Schmerz stammen aus bestätigten Angaben.

**Oberfläche:** In der Aktivitätsansicht der Abschnitt „Trainingsqualität“, mit Ziel/Ist-Tabelle und Grafik. Feedback wird entsprechend dem bestehenden Coach-Verhalten explizit erfasst; UI und Coach erhalten dieselbe Analyseprojektion.

**Abnahme:** Ein Training mit vollständiger Dauer kann korrekt einen verfehlten Intervallzweck zeigen. Geänderte heutige FTP verändert keine alte Bewertung. Pausen, verschobene Intervalle, fehlende Runden, Abbruch und fehlender RPE erzeugen nachvollziehbare Ergebnisse. Tages-RPE wird keiner Aktivität automatisch zugeschrieben.

## Paket 4 Ausdauerentwicklung und lange Belastungen

**Umsetzung:** Geeignete gleichmäßige Abschnitte lockerer Rad- und Laufeinheiten auswählen. Warm-up, Stopps, hohe Intensitätswechsel und unzureichende Sensorabdeckung kennzeichnen beziehungsweise ausschließen. Erst Provider-Decoupling mit Quellenlabel darstellen; eine eigene Berechnung wird separat mit dokumentierter Methodik eingeführt.

**Metriken:** Beim Rad Watt/Herzfrequenz, beim Laufen Geschwindigkeit/Herzfrequenz. Lokale Drift vergleicht die Effizienz zweier gleich langer geeigneter Abschnitte: `100 × (Effizienz zuerst − Effizienz danach) / Effizienz zuerst`. Die Stabilität langer Einheiten vergleicht passende frühe und späte Belastungsabschnitte; unterschiedliche Dauer, Intensität und Wetterbedingungen bleiben sichtbar. Ein universeller Drift-Grenzwert erzeugt keine pauschale Fitnessbewertung.

**Vergleich:** Einheiten nur innerhalb passender Sportart, Aufnahmeart und Belastungsbedingungen zusammenfassen. Indoor/Outdoor, Gelände und Temperatur berücksichtigen, soweit sie tatsächlich bekannt sind. Historische Vorhersagen sind kein gemessenes Wetter. Beim Laufen ist dies aerobe Effizienz, keine gemessene Laufökonomie. Ohne vergleichbare frühere Einheiten nur den aktuellen Messwert zeigen.

**Oberfläche und Owner:** „Ausdauerentwicklung“ unter Analyse → Leistung sowie dieselben Ergebnisse in der Aktivitätsansicht. Berechnung in `backend/performance/`, Auswahl und Referenzen über `backend/activities/`, Grafik über `public/analysis.js`.

**Abnahme:** Ein synthetischer gleichmäßiger Verlauf ergibt den erwarteten Effizienz- und Driftwert. Ein Verlauf mit steigendem Puls bei konstanter Leistung zeigt den korrekten Drift. Fehlende Herzfrequenz, Stopps und variable Intervalle erzeugen keine scheinbar belastbare Ausdauerverbesserung. Providerwert und eigene Methode werden nicht vermischt.

## Paket 5a Body

**Umsetzung:** Den Analyse-Tab ausdrücklich **Body** nennen. Die gemeinsame normalisierte Datenbasis führt Intervals-Wellness (`weight`, `bodyFat`) und Garmin-Körpermessungen zusammen. Zuerst den bereits geladenen `get_weigh_ins`-Datensatz auf KFA und vollständige Messungen prüfen; `get_body_composition(startdate, enddate)` nur ergänzen, wenn dort benötigte Felder fehlen. Kein doppelter Abruf identischer Messungen. Bei konkurrierenden Messungen bleiben beide Quellen, Messzeit und Abrufzeit sichtbar. Bestätigte manuelle Angaben bleiben im Profil maßgeblich und werden durch keinen Sync überschrieben; historische Messserien und manuelle Profilwerte sind getrennt.

**Diagramme:** Drei getrennte, mobile SVG-Diagramme zeigen Gewicht in kg, Körperfettanteil in Prozent und Rad-W/kg. Der Nutzer kann zwischen **14 Tagen** und **12 Wochen** wechseln; alle drei Karten verwenden denselben Zeitraum. Tagesansicht zeigt die letzte gültige Messung je Tag und Quelle. Die Wochenansicht zeigt den Median tatsächlich gemessener Gewicht-/KFA-/W/kg-Werte mit Anzahl und ursprünglichen Messdaten. Leere Tage beziehungsweise Wochen bleiben Lücken.

**W/kg:** Grundlage ist Rad-FTP in W geteilt durch Gewicht in kg. Intervals-eFTP und Garmin-FTP bleiben getrennte, beschriftete Serien. Garmin-Historie wird mit `get_functional_threshold_power_range(..., sport="CYCLING", aggregation="daily")` gelesen; der Bibliotheksstandard `RUNNING` ist für Rad-W/kg ungeeignet. Es werden nur Werte kombiniert, deren Gültigkeit zum Zeitpunkt nachvollziehbar ist. Als Startregel höchstens sieben Tage altes Gewicht verwenden und dessen Alter anzeigen; nie zukünftige Messungen rückwirkend zuordnen. Ein aktueller Profilwert allein erzeugt keine historische Kurve. Bei fehlender oder veralteter Grundlage erscheint `insufficient_data`. Wochenwerte werden aus gültigen täglichen Quotienten gebildet, nicht aus unabhängig gemittelten Eingangswerten.

**Owner und Abnahme:** `backend/performance/` normalisiert und berechnet, `backend/providers/garmin.py` und der bestehende Intervals-Sync sammeln, `public/analysis.js` rendert die drei Diagramme. Mobile-small zeigt jede Grafik mit lesbaren Achsen, Quelle und Messdatum ohne horizontales Überlaufen. Tests decken Providerwechsel, doppelte Messungen, Lücken, veraltetes FTP, KFA ohne Gewicht und einen 14-Tage-/12-Wochen-Wechsel ab. Keine medizinische Bewertung wird aus KFA oder Gewicht abgeleitet.

## Paket 5b Garmin-Tagesverbrauch im Ernährungstagebuch

**Umsetzung:** Den aktuellen, datierten Garmin-Gesamtverbrauch aus den bereits gesammelten Tagesstatistiken im Ernährungstagebuch anzeigen. `get_calories_daily(start, end)` ergänzt bei Bedarf aktive und Ruhekalorien sowie die Historie. Kein 7-Tage-Durchschnitt und keine bloße Summe der Trainingskalorien dient als Tagesverbrauch. Abweichende Endpunkte werden über eine dokumentierte Quellenregel aufgelöst. Die Daten kommen ausschließlich aus dem vorhandenen Garmin-Sync; das Öffnen des Tagebuchs liest lokalen Zustand.

**Aktueller Tag:** Beschriftung „Garmin-Tagesverbrauch · aktueller Schätzwert“ mit Abrufzeit und vorläufigem Status. Angezeigt wird der von Garmin bereitgestellte Wert für den ganzen Kalendertag einschließlich Ruhe-/Alltagsverbrauch. Eine bereits enthaltene Aktivitätsenergie wird nicht zusätzlich addiert. Die Ansicht erklärt, ob die Quelle einen bisher erfassten Wert oder eine Ganztagesschätzung liefert; sie extrapoliert nicht selbständig den restlichen Tag. Erst nach bestätigter Datenabdeckung gilt ein zurückliegender Tag als vollständig.

**Oberfläche:** Die Tageskarte zeigt zuerst den Gesamtverbrauch in kcal. Aktive und Ruhekalorien sind aufklappbar, soweit vorhanden. Aufnahme, Verbrauch und eine optionale Differenz werden klar getrennt; eine Differenz ist keine automatische Empfehlung und schreibt keinen Tagebucheintrag. Bei Sync-Fehler bleibt ein vorhandener Wert mit Veraltet-Hinweis sichtbar. Ohne Messung erscheint „Nicht verfügbar“; null wird nur bei tatsächlich gemessenem Nullwert angezeigt.

**Abnahme:** Tageswechsel und Athletenzeitzone stimmen, Teilwerte werden nicht doppelt addiert, fehlende Teilwerte werden als unvollständig markiert, und ein neuer Sync aktualisiert nur die betroffenen Tage. Der Garmin-Fehler darf Ernährung, Intervals-Sync oder andere Garmin-Bereiche nicht verwerfen.

**Bibliotheksdetail:** `get_calories_daily` gibt `calendarDate`, `active`, `resting` und `total` zurück. Die Bibliothek berechnet `total` mit `(active or 0) + (resting or 0)` auch bei fehlendem Teilwert. Der Adapter muss daher die Teilwerte prüfen; eine solche Summe darf nicht als vollständiger Gesamtverbrauch gelten. Ein legitimer gemessener Nullwert bleibt von `None` unterscheidbar.

## Paket 5 Persönliche Erholung und Schlaf

**Umsetzung:** Den neuen Analyse-Unterbereich Erholung einführen. HRV, Ruhepuls und Schlaf gegen persönliche datierte Verteilungen auswerten. Als vorgeschlagene Startregel ein gleitendes Fenster von 42 Tagen verwenden; unter 14 passenden Nächten keine Normalbereich-Einordnung ausgeben und bis 28 Nächten den Bereich als vorläufig kennzeichnen. Diese Zahlen sind Abdeckungsregeln für die erste Version, keine medizinischen Schwellen.

**Methodik:** Median und Quartile neben aktuellem Wert und Beobachtungsdatum zeigen. Gleichartige HRV-Messungen vergleichen; Messmethode und Providerwechsel trennen. Keine Mischung aus RMSSD, SDNN oder unterschiedlichen Messzeitpunkten. Einordnungen beschreiben Abweichungen vom eigenen Bereich. Eine Trainingsanpassung berücksichtigt zusätzlich Schmerzen, Krankheit, Motivation und bisherige Belastung.

**Schlaf:** Bestätigtes persönliches Schlafziel im Profil ergänzen. Das Defizit der letzten sieben Nächte aus bekannten Dauern und diesem Ziel ableiten, ohne einzelne lange Nächte als vollständigen Ausgleich zu behaupten. Schlafregelmäßigkeit nur mit tatsächlichen Schlafbeginn-/Endzeiten und korrekter Behandlung von Mitternacht, Zeitzone und Zeitumstellung anzeigen. Garmin-Schlafstadien bleiben Provider-Schätzungen.

**Provider-Erweiterung:** Vorhandene Intervals-Wellness-Werte für Müdigkeit, Muskelkater, Stress und Verletzung mit Quellenlabel nutzbar machen. Garmin-Stress, Atmung, SpO₂ und Hydration folgen als optionale Kontextreihen bei ausreichender Abdeckung. Messverfahren und fehlende Geräteunterstützung bleiben sichtbar. Diese Reihen ergänzen die bestehende Erholungsansicht; sie erzeugen keinen zweiten Readiness-Score.

**Oberfläche und Owner:** Analyse → Erholung enthält Tageskarte und Verläufe; im Kalender erscheint nur die kurze Einordnung mit Verknüpfung. Die vorhandenen Besitzer `backend/performance/recovery*.py`, `history.py`, `garmin_projection.py` und `backend/athlete/` erweitern. Gesundheitshistorie im bestehenden datierten Garmin-/Wellness-Pfad verfügbar halten.

**Abnahme:** Bei wenigen, veralteten oder inkompatiblen Messungen bleibt die Bewertung offen. Baselines enthalten keine zukünftigen Tage. Wechsel des Providers verschiebt den Normalbereich nicht unbemerkt. Fehlendes Schlafziel erzeugt kein erfundenes Defizit. Krankheit/Schmerz wird nicht durch eine günstige HRV relativiert.

## Paket 6 Leistungsprofil und wiederkehrende Trainings

**Umsetzung:** Für Radfahren zunächst beste beobachtete mittlere Leistung über 5 Sekunden, 1, 5 und 20 Minuten sowie eine Leistungs-Dauer-Kurve erstellen. Dafür zuerst Intervals `/athlete/{id}/power-curves`, `/athlete/{id}/activity-power-curves` und `/activity/{id}/best-efforts` prüfen; Garmin historische FTP-Werte über `get_functional_threshold_power_range` nur ergänzend verwenden. Für Laufen passende Geschwindigkeits-/Distanzbestwerte aus Pace-Kurven und Best Efforts anbieten. 28- und 90-Tage-Vergleiche genügen für die erste Version. Absolute Werte und W/kg werden nur mit passendem datiertem Gewicht angeboten.

**Vergleich:** Zuerst wiederkehrende Bibliotheksvorlagen und Indoor-Protokolle über stabile Referenzen vergleichen. Streckenvergleich folgt innerhalb dieses Pakets nur, wenn geeignete GPS-/Streckenreferenzen verfügbar sind. Strecke und Ergebnis werden innerhalb der privaten Anwendung verarbeitet. Eine manuelle Vergleichsgruppe ist möglich; die dauerhafte Zuordnung wird bestätigt gespeichert.

**Provider-Erweiterung:** `interval-search` findet Kandidaten mit ähnlicher Dauer und Intensität; `interval-stats` liefert Statistik für ausgewählte Aktivitätsabschnitte. Eine Provider-Suche allein beweist keine Vergleichbarkeit. Intervals-Power-Kurven können zusätzlich ermüdete Kurven (`-kj0`/`-kj1`) liefern: als spätere Erweiterung für Leistung nach Vorbelastung in Paket 4/6 einplanen, mit ausgewiesener Vorarbeit und Datendeckung. Herzfrequenzkurven sind Belastungskontext, keine Rangliste nach maximalem Puls.

**Grenzen:** Die Kurve zeigt beobachtete Bestleistungen. Weniger Maximalversuche bedeuten nicht automatisch Leistungsverlust. Eine genaue Critical-Power-/W′-Schätzung wird erst ergänzt, wenn belastbare Eingangsdaten und eine überprüfte Fit-Methode vorliegen. Xerts proprietäre Fitness-Signature und TrainerRoad-Levels werden nicht behauptet oder nachgebildet.

**Oberfläche und Owner:** Leistungsprofil unter Analyse → Leistung; „Vergleichen“ in der Aktivitätsansicht. `backend/performance/` berechnet Kurven; `backend/activities/` besitzt Auswahl und Gruppen.

**Abnahme:** Bestwerte sind bei ungleichmäßigen Sampleabständen korrekt. Verlorene Samples und Sensorausreißer erzeugen keine Rekorde. Jede Bestleistung führt zur Aktivität und zum Zeitabschnitt. Verschiedene Vorlagenrevisionen oder Messsysteme bleiben erkennbar.

## Paket 7 Wettkampfspezifische Vorbereitung

**Umsetzung:** Geplant um den Unterbereich Saison ergänzen. Einen Wettkampf auswählen und dessen Datum, Priorität, Sport, Distanz und bestätigtes Ziel mit absolviertem Training verbinden. Zuerst Halbmarathon/Marathon und lange Radevents unterstützen, anschließend weitere Wettkampftypen anhand ihrer verfügbaren Anforderungen.

**Auswertung:** Regelmäßigkeit, sportartspezifischer Umfang, lange Einheiten, passend absolvierte Schlüsseltrainings und Stabilität längerer Belastungen zeigen. VO₂max-/Provider-Zeitprognosen separat darstellen. Der Vorbereitungsstand besteht aus belegten Teilaspekten; er ist kein pauschaler Prozentwert. Für längere Vorbereitung kann ein begrenzter Zeitraum bis 180 Tage nötig sein; fehlende Historie bleibt sichtbar und wird nur auf ausdrücklichen Refresh ergänzt.

**Oberfläche und Coach:** Die vollständige Ansicht liegt in Saison; „Dein nächstes Ziel“ unter Analyse → Leistung zeigt die Zusammenfassung und verlinkt dorthin. „Vorbereitung besprechen“ gibt dem Coach konkrete Belege. Kalenderphasen werden nicht als Beweis der physiologischen Bereitschaft verwendet.

**Owner:** `backend/planning/season.py` für Saisonbezug, `backend/performance/` für die Auswertung, bestehende Competition-Domäne für Ziele und Datenänderungen.

**Abnahme:** Ein hoher VO₂max-Wert bei fehlenden langen Einheiten führt nicht zu uneingeschränkter Marathonbereitschaft. Radkilometer zählen nicht als Laufkilometer. Fehlende Distanz oder Zielzeit schränkt die passende Aussage ein. Ein geändertes Ziel aktualisiert die Auswertung, ohne einen Plan automatisch zu verändern.

## Paket 8 Plan-Simulation

**Umsetzung:** In Saison zwei Szenarien gegenüberstellen: aktueller Plan und eine explizite Alternative, etwa geringerer Wochenumfang oder zusätzliche Entlastung. Mit geplanten lokalen Einheiten, tatsächlicher Ausgangsbelastung und bekannten Load-Parametern Belastung/Form bis zum Wettkampf projizieren.

**Modell:** Startzustand, Zeitkonstanten, Methode und Annahmen sichtbar machen. Ist die Providerkonfiguration nicht bekannt, entweder eine ausdrücklich bezeichnete lokale Standardmodellierung verwenden oder den entsprechenden Vergleich offenlassen. Fehlende geplante Belastung bleibt eine gekennzeichnete Annahme. CTL ist keine Prognose für FTP, Gesundheit oder Wettkampfzeit.

**Freigabe:** Rechnen verändert keine Planung. Ein gewähltes Szenario wird anschließend in die vorhandene adaptive Vorschau überführt. Erst die ausdrückliche Freigabe ändert zukünftige lokale Einheiten; vor Anwendung Planrevision, Datum und Constraints erneut prüfen. Remote-Sync bleibt eine eigene ausdrückliche Aktion.

**Owner:** Modellierung unter `backend/performance/load*.py`, Szenarien und Anwendung unter `backend/planning/`, Anbindung über vorhandene Coach-Planvorschau. Kein neues Planungsframework.

**Abnahme:** Derselbe Eingangszustand erzeugt dasselbe Szenario. Neue Aktivitäten oder Planänderungen machen eine ältere Vorschau erkennbar veraltet. Ein Race-Taper wird in der Belastungsprojektion sichtbar, ohne eine präzise Leistungssteigerung zu versprechen. Berechnen und Abbrechen hinterlassen den Plan unverändert.

## Paket 9 Trainingsverpflegung

**Umsetzung:** Ernährung um Trainingsverpflegung ergänzen. Eine geplante Einheit auswählen und Dauer, Intensität, Tageszeit, bestätigte Verträglichkeit, verfügbare Mahlzeiten und tatsächlich verfügbare Wetterdaten berücksichtigen. Zunächst Ausdauertraining unterstützen.

**Ergebnis:** Vorschläge für vorher, währenddessen und danach: Kohlenhydratbereich pro Stunde, praktikable Portionen, Getränkebereich und geeignete Mahlzeiten. Startbereiche fachlich begründen und als Empfehlungen kennzeichnen. Aus Puls oder FTP wird weder exakter Glykogenverbrauch noch eine individuelle Schweiß-/Natriumrate errechnet. Anpassungen an die Verträglichkeit werden bestätigt im Profil gespeichert.

**Daten und Coach:** Lebensmittelwerte und Portionen durch den bestehenden `FoodDatabaseService` und Nutrition-Service berechnen. Ein bestätigter Verpflegungsplan speichert die zugehörige lokale Einheit und deren Revision. Mahlzeitenvorlagen bleiben unabhängig. Verzehr wird erst nach tatsächlicher, ausdrücklich erfasster Aufnahme ins Tagebuch geschrieben; Planung erzeugt keinen Ernährungseintrag.

**Tagesenergie:** Paket 5b stellt Garmin-Verbrauch bereit. Intervals `kcalConsumed`, `carbohydrates`, `protein` und `fatTotal` können optional als externe Referenz angezeigt werden. Das lokale, ausdrücklich geführte Tagebuch bleibt maßgeblich; Provideraufnahme wird nicht automatisch als zweite Mahlzeit importiert. Garmin-Hydration kann eine getrennte Trinkmengenreferenz ergänzen, sofern sie tatsächlich protokolliert wurde.

**Oberfläche:** Kurzer Hinweis in der geplanten Einheit, vollständige zeitliche Abfolge unter Ernährung → Trainingsverpflegung. Dort „Mit dem Coach anpassen“ und „Verzehr erfassen“ als unterschiedliche Aktionen.

**Abnahme:** Änderung von Dauer oder Intensität kennzeichnet einen älteren Vorschlag als überholt. Unvollständiges Ernährungstagebuch ergibt keinen sicheren Energiemangel. Portionen und Nährwerte stimmen mit gespeicherten Vorlagen überein. Hypothetischer oder verneinter Verzehr wird nicht gespeichert.

## Paket 10 Persönliche Einflussanalyse

**Umsetzung:** Tages-Check-ins um ausdrücklich gesetzte Tags ergänzen, etwa Reise, spätes Essen oder hoher Stress. Freitext nicht automatisch in vermeintliche Fakten umwandeln. Tags und Erholungsdaten über die Athletenzeitzone sowie die nachfolgende Nacht korrekt verbinden.

**Auswertung:** Für einen gewählten Zeitraum Anzahl, Median und Streuung von Erholung/Schlaf mit und ohne Tag vergleichen. Als vorgeschlagene Startregel mindestens zehn bekannte Tage je Gruppe verlangen; fehlendes Tag bedeutet nur dann „ohne“, wenn der Check-in diese Einordnung tatsächlich erlaubt. Unterschiede der Belastung und Datenabdeckung daneben zeigen. Mehrere gleichzeitig gesetzte Tags bleiben erkennbar.

**Oberfläche und Owner:** Unter Analyse → Erholung „Was beeinflusst deine Erholung?“. Tags unter `backend/athlete/`, Auswertung unter `backend/performance/`. Der Coach erklärt beobachtete Zusammenhänge ohne Kausalitäts- oder Diagnosebehauptung.

**Abnahme:** Wenig Daten, selektive Erfassung, fehlende Gruppenzuordnung oder Providerwechsel führen zu einer eingeschränkten Aussage. Korrigierte Tags aktualisieren das Ergebnis. Ungetaggte Tage werden nicht als bestätigter Verzicht auf Alkohol, spätes Essen oder andere Einflüsse interpretiert.

## Paket 11 Geprüfte Intervals-/Garmin-Erweiterungen

Die folgenden Daten sind in der offiziellen Intervals.icu-Open-API beziehungsweise in `garminconnect==0.3.17` vorhanden, werden aktuell aber nicht vollständig genutzt. Sie werden nur aufgenommen, wenn eine konkrete lokale Ansicht oder Berechnung den Nutzen belegt. Jeder Abruf bleibt optional, erhält Capability-, Fehler- und Freshness-Metadaten und darf den übrigen Sync nicht ausfallen lassen.

**Priorität 1 – direkt in bestehende Pakete einbauen:**

- Intervals `/athlete/{id}/power-curves`, `/athlete/{id}/pace-curves` und `/athlete/{id}/hr-curves` sowie die Aktivitätsvarianten für robuste Leistungs-, Pace- und Herzfrequenzverläufe. Diese speisen Paket 6, ohne Bestwerte aus der begrenzten Coach-Projektion zu berechnen. Bestleistungen werden im Body-Tab nicht stillschweigend als FTP verwendet.
- Intervals `/activity/{id}/best-efforts`, `/athlete/{id}/activities/interval-search` und `/activity/{id}/interval-stats`. Sie ergänzen Paket 1 und 3 um belegte Bestleistungen, ähnliche Einheiten und wiederholbare Intervallvergleiche.
- Garmin-Körperzusammensetzung und Tageskalorien sind verbindliche Ergebnisse von Paket 5a/5b. `get_body_composition` und `get_calories_daily` sind zusätzliche Datenwege, wenn vorhandene Gewichts-/Tagesstatistiken die benötigten Felder nicht liefern.
- Garmin `get_functional_threshold_power_range` für historische FTP-Werte. Es verhindert, dass eine aktuelle Schwelle ältere W/kg- oder Intervallbewertungen verfälscht.

**Priorität 2 – Aktivitätsverständnis und Erholung:**

- Intervals `/activity/{id}/weather-summary`, `/activity/{id}/map`, `/activity/{id}/power-vs-hr`, `/activity/{id}/power-histogram`, `/activity/{id}/pace-histogram`, `/activity/{id}/hr-histogram` und `/activity/{id}/gap-histogram`. Wetter, Strecke, Gelände und Effizienz werden in der Aktivitätsansicht nur angezeigt, wenn sie für die konkrete Aktivität vorhanden sind; keine nachträgliche Wetterbehauptung aus einer Prognose. Garmin `get_activity_weather`, `get_activity_splits` und `get_activity_split_summaries` sind mögliche Alternativen bei Garmin-only-Aktivitäten. Keine doppelten Detailreihen derselben Aufzeichnung; rohe Routenkoordinaten bleiben außerhalb des Coach-Kontexts.
- Garmin `get_endurance_score`, `get_hill_score` und `get_running_tolerance` als getrennte Providerwerte unter Analyse → Leistung. Sie werden nicht mit eigener Fitness- oder Wettkampfberechnung verrechnet. Beim Endurance Score liefert ein Datumsbereich aggregierte Wochenwerte; diese dürfen nicht als tägliche Messungen erscheinen. Running Tolerance unterstützt tägliche oder wöchentliche Aggregation und muss entsprechend beschriftet sein.
- Garmin `get_intensity_minutes_data`, `get_weekly_intensity_minutes`, `get_weekly_steps` und `get_weekly_stress` als optionale Wochenkontextwerte. Sie ergänzen den Wochenrückblick, ersetzen aber keine sportartspezifische Belastungsanalyse. Garmin-Intensitätsminuten können anders gewichtet sein als tatsächliche Trainingsdauer und werden nicht als Zonenzeit ausgegeben.
- Intervals-Wellness `soreness`, `fatigue`, `stress`, `injury`, `spO2`, `hydration`, `respiration`, `steps`, `carbohydrates`, `protein` und `fatTotal`. Zunächst nur Felder mit ausreichender Abdeckung und nachvollziehbarer Darstellung aktivieren; keine automatische Gesundheitsbewertung aus Einzelwerten.

**Priorität 3 – spätere, getrennte Erweiterung:**

- Garmin `get_stress_data`, `get_respiration_data`, `get_spo2_data` und `get_hydration_data` für die Erholungskarte, jeweils mit Messzeit und Geräte-/Providerhinweis.
- Garmin `get_activity_exercise_sets` für Krafttraining. Übungssätze gehören in eine eigene Aktivitätsdetailkarte und werden nicht aus Herzfrequenz oder Kalorien in Ausdauerbelastung umgerechnet.
- Garmin `get_devices`, `get_training_plans`, `get_scheduled_workouts` und Detailmethoden können später Gerätefähigkeit und einen ausdrücklich angeforderten Planvergleich erklären. Intervals-Sport-/Zoneneinstellungen kommen nur hinzu, wenn sie eine konkrete Berechnung fundieren; aktuelle Einstellungen sind kein Ersatz für fehlende historische Schwellen. Automatische Planübernahme und Geräteübertragung sind separate Nutzeraufträge.

**Abnahme und Reihenfolge:** Priorität 1 wird in den jeweiligen Paketen umgesetzt; Paket 11 bündelt die nachfolgenden Ergänzungen. Für jeden aktivierten Abruf gibt es synthetische Antwort-Fixtures und einen optionalen Fehlerfall. Ein fehlender Endpunkt erzeugt einen erklärten Bereichsstatus, keine Nullserie. Für Priorität 2 werden Datenabdeckung, Quellenwechsel und UI-Platzbedarf auf mobile-small geprüft. Vor neuen dauerhaften Zeitreihen wird entschieden, ob vorhandene Snapshot-Persistenz ausreicht; andernfalls sind SQLCipher-Migration, Export und Restore Bestandteil derselben Lieferung.

## Paket 12 Ausrüstung

**Festgestelltes Problem:** `renderTrainingRecords` in `public/analysis.js` gruppiert nach Sport, aber nicht nach aktiv/ausgemustert. Garmin-Karten erscheinen direkt; der allgemeine lokale `<details>`-Block mischt aktive und archivierte Einträge. Ein eigener Archivbereich fehlt. Der Lebensdauerbalken existiert nur in `garminEquipmentCard` für die Übergangsprojektion `garmin_items`. Nach dem Erstimport setzt `EquipmentService.read` diese Liste leer und liefert Garmin-verknüpfte Gegenstände als lokale `items`; `localEquipmentCard` zeichnet keinen Balken. Zusätzlich speichert `_insert_initial_garmin_item` das Garmin-Ziel `maximumMeters` nicht. Der Fehler betrifft somit Datenprojektion und Renderer; ein CSS-Fix allein stellt den Balken nicht wieder her.

**Umsetzung:** Die vorhandene Ausrüstungsansicht unter Mehr → Ausrüstung und Wartung reparieren: Schuhe, Fahrrad und Komponenten, Sportart, Status, Anfangsstand und persönliche Ziele. Einheiten über eine stabile Referenz zuordnen; Erfassung und Änderungen werden ausdrücklich bestätigt. Bestehende `items`/`garmin_items` für UI und Coach kompatibel erweitern, statt eine zweite Verwaltung einzuführen. Beide erhalten normalisierten Status und dieselbe begrenzte Lebensdauerprojektion. Die Rohbezeichnung von Garmin bleibt als Provenienz erhalten, steuert aber nicht direkt die Darstellung.

**Darstellung:** Aktive Hauptausrüstung und aktive Komponenten werden zuerst angezeigt. Ausgemusterte beziehungsweise archivierte Einträge werden standardmäßig aus der aktiven Liste entfernt und je Sportart in genau einem geschlossenen `<details>`-Bereich „Ausgemusterte Ausrüstung (N)“ gesammelt, einschließlich Komponenten. Der Bereich enthält lokale und Garmin-Einträge, zeigt ihren letzten bekannten Stand und bleibt bei null Einträgen unsichtbar. Archivierte Gegenstände bleiben in alten Aktivitäten referenzierbar und sind für neue Zuordnungen nicht auswählbar. Unbekannter Status erhält einen erklärten Zustand und wird nicht pauschal aus dem Namen abgeleitet.

**Lebensdauerbalken:** Das Garmin-Lebensdauerziel `maximumMeters` beim Erstimport erhalten und in km normalisieren. Bereits importierte Gegenstände über `garmin_uuid` mit einem gültigen Ziel im vorhandenen Snapshot ergänzen; ein bestätigtes lokales Ziel darf dabei nicht überschrieben werden. Fehlt das Ziel auch dort, gezielt im regulären Sync ergänzen oder über den Coach ausdrücklich erfassen. Lokal angelegte Gegenstände können ein bestätigtes Lebensdauerziel in km oder Stunden erhalten. Eine gemeinsame Leseprojektion liefert bekannte Nutzung, Ziel, Prozentwert, Einheit, Quelle und Abdeckung für beide Kartenarten. Garmin-Kilometer werden weiterhin führend übernommen und niemals zusätzlich zu denselben lokalen Aktivitätskilometern addiert.

Der Balken zeigt verbrauchte Lebensdauer mit sichtbarem Text wie „250 von 1.000 km · 25 %“ und zugänglicher Beschriftung. Die Füllung bleibt zwischen 0 und 100 %, während der Text einen überschrittenen Wert wie 120 % mit „Ziel überschritten“ bewahrt. Ein echter Nullstand zeigt 0 %; fehlende Werte erscheinen als unbekannt. Ein Ziel muss positiv sein, Nutzung darf nicht negativ oder nichtendlich sein. Ohne Ziel oder Zähler erscheint eine präzise Erklärung ohne irreführenden Balken. Wartungsintervalle bleiben separat als „Seit letzter Wartung“ gekennzeichnet: Wartung darf die gesamte Lebensdauernutzung nicht zurücksetzen.

**Status und Datenhoheit:** Beim Erstimport die tatsächlich unterstützten Garmin-Statusfelder und Werte normalisieren, einschließlich retired/archived/inactive. Nach dem Import bleibt der bestätigte lokale Lebenszyklus maßgeblich; der Garmin-Sync überschreibt keine lokale Archivierung, Reaktivierung oder Komponenten-Zuordnung. Abweichender Garmin-Status wird als Quellenkonflikt kenntlich und kann über eine ausdrückliche Coach-Aktion übernommen werden. Fehlt ein Gegenstand im nächsten Snapshot, gilt dies nicht als Löschung oder automatische Ausmusterung. Ziel, Status und Nutzung bleiben im Backup-/Exportpfad erhalten; vorhandene KV-Daten werden kompatibel erweitert.

**Mobile UX:** Die Sporttabs bleiben erhalten. Aktive Karten haben eine kompakte Kennzahl, den Balken und den Status; Wartungshistorie und ausgemusterte Karten sind aufklappbar. Auf 320–390 px darf kein horizontaler Überlauf entstehen. Der Summary-Text nennt Anzahl und letzte Aktualisierung, damit ausgemusterte Komponenten auffindbar bleiben, ohne den aktiven Bereich zu überladen.

**Zähler:** Kilometer, Nutzungszeit und Wartungsstand aus kanonischen Aktivitäten und bestätigtem Anfangsstand ableiten. Wechsel einer Komponente bekommt einen eigenen Start-/Wartungszeitpunkt. Fehlende Zuordnung zählt nicht automatisch zum bevorzugten Fahrrad oder Schuh. Provider-Duplikate, korrigierte Distanz und Archivierung werden bei der Ableitung berücksichtigt.

**Oberfläche:** Ausrüstung beim Aktivitätsfeedback zuordnen; aktive Ausrüstung erhält den einheitlichen Lebensdauerbalken und persönliche Wartungshinweise in Aktivitätsdetails sowie beim betroffenen Gegenstand. Historische Aktivitätsreferenzen dürfen archivierte Gegenstände verlinken, aber keine neue Zuordnung erlauben. Hinweise beschreiben erreichte Nutzerintervalle und behaupten keine Material- oder Verletzungsdiagnose.

**Owner:** Athletenbezogene Ausrüstungsdaten unter `backend/athlete/`, Aktivitätszuordnung unter `backend/activities/`, vorhandene Coach-Schreibwege entsprechend erweitern. Keine eigenständige neue Navigationsrubrik nötig.

**Abnahme:** Eine doppelt aufgezeichnete Fahrt zählt einmal. Umbuchung auf einen anderen Schuh korrigiert beide Zähler. Wartung setzt nur den betreffenden Wartungszähler zurück und löscht keine Historie. Archivierte Gegenstände bleiben in älteren Einheiten referenzierbar, erscheinen aber standardmäßig nur im geschlossenen Archivbereich. Garmin-Status „retired“, „archived“ und „inactive“ werden normalisiert und gemeinsam mit lokal archivierten Einträgen geprüft. Tests decken Garmin-Ziele in Metern, lokale km-/Stundenlimits, unbekannte Zähler, fehlende Limits, 0-%- und über-100-%-Werte, aktive Komponenten, archivierte Komponenten, gemischte Quellen, Zähleraktualisierung und mobile Ausklappbarkeit ab. Browser-Abnahme prüft `progress`-Wert, sichtbaren Text, `aria-label`, geschlossenen Archivbereich und `scrollWidth <= innerWidth` auf mobile-small.

## Prüfung und Abschluss jedes Pakets

Für jedes Paket zuerst fokussierte Unit-Tests mit synthetischen Zeitreihen, temporärer Datenbank und gemockten Providern. Relevante Fälle sind Datenlücken, Zeitumstellung, ungleichmäßige Messabstände, Duplikate, geänderte Schwellen, Wiederholungen, Abbruch und veraltete Referenzen. Analysen benötigen bekannte Eingänge mit fachlich nachvollziehbaren erwarteten Ergebnissen; reine Spiegeltests des Implementierungscodes genügen nicht.

Bei Backend-Änderungen Ruff, Formatprüfung, mypy und `python -m compileall -q server.py backend tests` ausführen. Vor Abschluss einer Feature-PR die vollständige Unit-Suite ausführen. Bei Schema-Änderungen Schema-Vertrag, frische SQLCipher-Initialisierung, Same-build-Restart, Privacy-Export und Restore eines aktuellen Backups prüfen.

Schemaänderungen enthalten außerdem eine eingefrorene Fixture des vorherigen Release-Schemas mit bestehenden Daten, direkte Upgrades der unterstützten Releases einschließlich übersprungener Zwischenversionen sowie Rollback bei fehlgeschlagener Migration. Backup-/Exportlisten und die Standard-Fixture werden in derselben PR angepasst; ein leeres Datenverzeichnis ist kein Upgrade-Nachweis.

Browser-Flows auf mobile-small und desktop prüfen; zusätzliche Projekte wählen, wenn Layout oder Interaktion sie betrifft. Die Integration läuft mit einem frisch gebauten Docker-Image, isoliertem Fixture-Datenverzeichnis und frischem Browserprofil. Login/CSRF, sichere Texte/Markdown, Kalender-Zurücknavigation, Enter/Shift+Enter, PWA-Assets, Offlinezustand und relevante Berechtigungsabläufe erhalten ihre bestehenden Verträge. UI-Änderungen synchronisieren Assetversionen, Service-Worker-Cache und Contract-Tests.

Coach-Prüfungen decken direkte Aufträge, Rückfragen, Korrekturen, Verneinung und hypothetische Aussagen ab. UI und Coach verwenden dieselben berechneten Fakten. Providerdaten bleiben untrusted; Belege und Metadaten werden bereinigt. Auswertung und Erklärung speichern weder Profile noch Training noch Verzehr. Durable Änderungen brauchen die passende ausdrückliche Aktion; adaptive Planung braucht Vorschau und Freigabe. Eine Live-AI-Evaluation ist ein gesonderter, ausdrücklich autorisierter Schritt.

Jede PR beschreibt auf Englisch Nutzerproblem, Ergebnis, Abhängigkeit und Prüfung, mit Conventional-Commit-Titel. Vor der PR auf den aktuellen Zielbranch rebasen, Konflikte prüfen und Mergefähigkeit bestätigen. Keine Veröffentlichung im Rahmen der Planerstellung.

## Erste Lieferung und nächster Umsetzungsschritt

Der gemeldete Ausrüstungsfehler aus Paket 12 gehört ebenfalls zur ersten Lieferung: geschlossener Archivbereich für ausgemusterte Komponenten und ein Lebensdauerbalken für lokale sowie Garmin-verknüpfte Gegenstände. Weitergehende Aktivitätszuordnungen und neue Wartungsabläufe aus Paket 12 bleiben nachfolgende Erweiterungen. Die Standard-Fixture enthält aktive und ausgemusterte Komponenten, fehlende Ziele, einen echten Nullstand und ein überschrittenes Lebensdauerziel; die mobile Abnahme prüft alle diese Zustände.

Die nächste Lieferung umfasst zuerst **Paket 0**, danach **5a und 5b**: beide Kalender-Flags zuverlässig beachten, Körperentwicklung im Tab Body zeigen und Garmin-Tagesverbrauch im Ernährungstagebuch lesen. Die Pakete können getrennte PRs bilden; die normalisierte Körper-/Tagesdatenbasis muss vor ihrer Darstellung verfügbar sein. Anschließend werden Leistungsprofile und Aktivitätsdetails aus Priorität 1 ergänzt. Weitere Erholungs-, Belastbarkeits- und Kraftdaten folgen anhand ihres konkreten Nutzens und ihrer Verfügbarkeit.

Der konkrete nächste Schritt ist Paket 0: die beiden Fehlerfälle mit synthetischen iCal-Terminen reproduzierbar machen, eine gemeinsame Prüfung für `[NO_TRAINING]` und `[NO_INTENSITY]` implementieren und alle betroffenen Schreibwege daran anschließen. Die erste PR enthält sichtbare Kalenderhinweise und Backend-Abnahme für beide Flags. Danach Körper-/Kaloriendaten normalisieren und Body sowie die Ernährungskarte ergänzen.

### Standard-Testdaten für die mobile Vorschau

Die isolierte Docker-Fixture erhält einen wiederholbar ladbaren Standarddatensatz mit mindestens 12 Wochen realistischen synthetischen Daten. Er deckt Gewicht, sporadische KFA-Messungen, datierte FTP-/eFTP-Änderungen, legitime Nullwerte, Lücken, Quellenwechsel und Garmin-Verbrauch einschließlich unvollständigem aktuellem Tag ab. Kalenderbeispiele enthalten beide Flags einzeln und kombiniert, Titel-/Beschreibungsmischungen, Serienausnahmen, mehrtägige und stornierte Termine sowie Konflikte mit bereits geplanten Einheiten. Außerdem bleiben Ernährung, Aktivitäten, Erholung, Coach, Wettkämpfe und Ausrüstung sinnvoll befüllt.

Der Standard wird als synthetische Fixture im Repository versioniert und in einem getrennten Test-Container geladen. Relative Datumsanker halten die Vorschau aktuell; Inhalt und Seed-Version bleiben reproduzierbar. Er benötigt weder Live-Accounts noch Garmin-Token und verändert keine echten Athletendaten. Die mobile Vorschau ist der gemeinsame Einstieg zum Sammeln weiterer Probleme und Feature-Ideen.

## Geprüfte API-Erweiterungen und Primärquellen

Am 6. Oktober 2026 wurden die öffentliche Intervals-Spezifikation sowie Methoden, Signaturen und relevante Implementierungen der Bibliothek **0.3.17 im laufenden Fixture-Image** abgeglichen. Das bestätigt die dokumentierte Schnittstelle, nicht die Verfügbarkeit auf einem konkreten Garmin-Gerät oder Konto. Es wurden keine Live-Provider-Accounts abgefragt.

| Quelle | Geprüfter Umfang | Konsequenz |
| --- | --- | --- |
| Intervals OpenAPI | Kurven einschließlich ermüdeter Power-Kurven, Best Efforts, Intervallsuche/-statistik, Wetter, Karte, Histogramme und Wellness-Felder | Abrufe anhand konkreter Auswertungen ergänzen; Parameter und Antwortschema je Endpunkt dokumentieren |
| Garmin 0.3.17 | Körperzusammensetzung, Tageskalorien, historische FTP, zusätzliche Gesundheitsdaten, Scores, Laufbelastbarkeit, Intensitätsminuten und Übungssätze | Geräte-/Kontoverfügbarkeit gesondert erkennen; neue Bereichsfehler isolieren |
| Garmin-Aggregation | Endurance-Range kann Wochenwerte liefern; FTP-Sport ist standardmäßig `RUNNING`; Calories Daily ersetzt fehlende Summanden intern durch null | Aggregation erhalten, `CYCLING` explizit setzen und Teilwerte vor Verwendung als Gesamtwert prüfen |
| Intervals athlete-summary | Zusammenfassung gefolgter Athleten; Bearer-Token beschränkt auf den eigenen Athleten | Kein zusätzlicher Abruf ohne konkreten Nutzen für die bestehende Ein-Athleten-App |

- [Intervals.icu Open API](https://www.intervals.icu/features/open-api/)
- [Intervals.icu OpenAPI-Spezifikation](https://intervals.icu/api/v1/docs) – Pfade einschließlich `/api/v1`, bei Kurven optionalem `{ext}`; die verkürzten Pfade im Plan beziehen sich auf diese Basis.
- [python-garminconnect Repository](https://github.com/cyberjunky/python-garminconnect)
- [Garmin Connect Bibliothek 0.3.17 auf PyPI](https://pypi.org/project/garminconnect/0.3.17/)

## Vergleichsquellen

Die Plattformen dienen als Produktinspiration. Die Berechnungen werden unabhängig dokumentiert und mit den tatsächlich verfügbaren Daten geprüft.

- [Intervals.icu Decoupling](https://www.intervals.icu/features/decoupling/) und [Power Curve](https://www.intervals.icu/features/power-curve/).
- [TrainerRoad Workout Levels](https://support.trainerroad.com/hc/trainerroad-support/articles/360061003592-workout-levels).
- [Runalyze Funktionen](https://runalyze.com/) und [Marathon Shape](https://runalyze.com/help/article/marathon-shape).
- [Athlytic persönliche Erholung und Journal](https://athlyticapp.com/getting-started/).
- [Xert Funktionen und Forecast](https://www.baronbiosys.com/features/).
- [TrainingPeaks Fueling Insights](https://www.trainingpeaks.com/coach-blog/fueling-insights-inigo-san-millan-carbohydrate-intake/).

## Abschluss der ersten Lieferung

Worker: gpt-6-luna, Reasoning high; Prüfung und Übernahme durch den Orchestrator.

| Umfang | Status |
| --- | --- |
| Paket 0: beide Kalender-Flags | Lokal umgesetzt und geprüft |
| Paket 5a: Body mit drei Diagrammen und zwei Zeiträumen | Lokal umgesetzt und geprüft |
| Paket 5b: Garmin-Tagesverbrauch | Lokal umgesetzt und geprüft |
| Paket 12: Archiv und Lebensdauerbalken | Gemeldete Fehler lokal behoben; weitere Zuordnungsfunktionen bleiben geplant |
| Standard-Testdaten | Versionierte synthetische Fixture, idempotenter Seed und Upgrade |
| Zusätzliche API-Features | Bewerteter Backlog; noch keine Umsetzung |

Abnahme: 3.308 Unit-Tests (16 übersprungen), 11 SQLCipher-Migrationsprüfungen, sechs Standard-Fixture-Tests sowie Body-, Ernährungs- und Ausrüstungs-Browserabläufe auf 320 px, 390 px und Desktop. PWA-Offline- und Markdown-Verträge bestanden. Ruff, gezieltes mypy, Syntaxprüfung und Docker-Build bestanden. Die Vorschau läuft lokal auf http://127.0.0.1:8091 in der mobilen Ansicht. Keine PR, Veröffentlichung oder produktive Bereitstellung wurde ausgelöst.

## Offene Punkte (Stand 7. Oktober 2026)

Erledigt: Der Wochen-Tab wurde entfernt. Stattdessen zeigt Analyse → Belastung ein Trainingszeit-Diagramm (14 Tage täglich, 12 Wochen als Wochensumme; Quelle `history.training_time`). Trainingsverpflegung, Körperverlauf und Schlafregelmäßigkeit im Coach sind umgesetzt. Auf Wunsch aus der Analyse-UI entfernt: Vergleichbare Einheiten, Einfluss von Check-in-Tags, Schlafdefizit und Schlafregelmäßigkeit (die Backend-Endpunkte bleiben bestehen). Versionen: analysis v88, styles v276, nutrition v17, Cache v357.

- Paket 12 (Ausrüstung): Umhängen (`assign`, überschreibt die Zuordnung) und Wartungszähler zurücksetzen (`maintain`, neues Wartungsdatum) sind im Backend und über die Coach-Tools vorhanden und getestet; eine eigene UI-Schaltfläche ist bewusst offen. Dubletten Garmin/lokal werden über `garmin_uuid` verknüpft.
- `[SHORT_ONLY]` ist erledigt: zentral in `calendar_constraint_decision` (blockiert Einheiten über 60 min, unbekannte Dauer bleibt erlaubt).
- Playwright `analysis-info` und `training-feature-panels` (mobile) wurden ausgeführt; drei Abweichungen wurden behoben (Spec-Texte, NaN bei unbekannter Wartungsnutzung).

Erledigt (Analyse → Leistung): Garmin-Provider-Metriken ohne Rohtexte, nun je Metrik ein Diagramm (Endurance Score, Running Tolerance). Ausdauer-Effizienz als Diagramm je Sportart (ab 2 Datenpunkten). Beste Fenster je Aktivität als schlichte Tabelle ohne Buttons. Leistungsprofil mit 28- und 90-Tage-Fenstern entfernt. Versionen: analysis v89, styles v277, Cache v358.

Erledigt: Seed-Skript `scripts/demo-container.ps1` (Demo-Container seedet beim Start selbst, optional mit Volume). Wartung erledigt: Button an aktiver lokaler Ausrüstung über `POST /api/equipment/maintenance`; Umhängen bleibt über den Coach. Ruff: Die offenen Meldungen in geänderten Dateien kamen aus `tests/test_server_frontend.py` und sind bereinigt, die übrigen Repo-Meldungen waren schon vorher vorhanden. Versionen: analysis v90, styles v277, Cache v359.
