# Umsetzungsplan für Trainingsanalysen und neue Funktionen

Stand: 2. Oktober 2026. Grundlage ist Commit `2adf195189d98a270b63d3e5a307c804fcb88c08` auf `t3code/training-platform-feature-research`. Status: geplant.

Der Plan ergänzt Intervals Coach um nachvollziehbare Trainingsanalysen, persönliche Erholung, Wettkampfvorbereitung und praktische Trainingsfunktionen. Die erste Lieferung verbindet Kalenderdetails, einen Wochenrückblick, Intervallqualität und Ausdauerentwicklung. Weitere Lieferungen ergänzen Erholung, Leistungsprofile, Planungsszenarien, Verpflegung, Einflussanalysen und Ausrüstung.

Jedes Arbeitspaket liefert einen nutzbaren Ablauf mit Backend, HTTP/API, Coach-Anbindung, Oberfläche und passenden Tests. Die Funktionen entstehen in getrennten PRs; größere Pakete werden entlang ihrer beschriebenen Teilschritte aufgeteilt. Dieser Plan beauftragt keine Veröffentlichung oder Umstellung einer bestehenden Installation.

## Geprüfte Grundlage

| Bereich | Bereits vorhanden | Konsequenz für die Umsetzung |
| --- | --- | --- |
| Analyse | Zwei SVG-Diagramme für Belastung/Form und relative Leistungsentwicklung über 90 Tage; Quellen und Datenlücken bleiben getrennt | `public/analysis.js` und `backend/performance/chart_history.py` erweitern; bestehende Diagramme weiterverwenden |
| Kalender | Geplante und absolvierte Einheiten, konservative Paarung und Soll-Ist-Vergleich nach Belastung oder Dauer | Aktivitätsdetails aus dem Kalender öffnen; der entfernte Verlauf-Tab bleibt entfernt |
| Detaildaten | `ActivityReadService.detail` liest genau eine Aktivität aus `raw_provider_data`; Coach-Projektion unterstützt vorhandene Streams und Runden | Verfügbarkeit vollständiger Streams zuerst absichern; die Projektion lädt sie nicht selbst |
| Intervals-Sync | `IntervalsSnapshotReader.fetch_snapshot` lädt Aktivitäten, Wellness, Events und Athletenwerte | Gezielte Detailabfragen über den bestehenden Sync ergänzen; Listenabrufe garantieren keine vollständigen Zeitreihen |
| Gesundheitsdaten | Garmin-/Intervals-Werte, datierte Verläufe und Durchschnittsvergleiche | Persönliche Normalbereiche und Schlafauswertungen als zusätzliche Berechnungen implementieren |
| Rückmeldungen | Aktivitätsfeedback speichert Freitext; Tages-Check-ins enthalten unter anderem Session-RPE | RPE je Aktivität strukturiert ergänzen; Tages-RPE nicht mehreren Einheiten zuordnen |
| Saison | Wettkämpfe und eine datumsbasierte Phasenzuordnung in `backend/planning/season.py` | Wettkampfeignung aus absolviertem Training getrennt von der kalendarischen Phase bewerten |
| Ernährung | Tagebuch, Mahlzeitenvorlagen, Lebensmittelberechnung und explizite Erfassung über den Coach | Trainingsverpflegung auf vorhandene Lebensmittel und Vorlagen aufbauen |
| Dauerhafte Daten | Aktuelles SQLCipher-Schema, Backup und explizite Exportlisten | Neue Felder und Tabellen zusammen mit Schema-Prüfung, Export und Restore-Verträgen ergänzen |

## Oberfläche und Einstiegspunkte

Die Hauptnavigation bleibt `Coach`, `Geplant`, `Analyse`, `Ernährung`, `Mehr`. Neue Unterbereiche werden mit dem jeweiligen Feature eingeführt.

| Ort | Geplante Inhalte |
| --- | --- |
| Analyse → Leistung | Vorhandene Diagramme, Ausdauerentwicklung, Leistungsprofil und wiederkehrende Trainings |
| Analyse → Aktuelle Woche | Automatischer Bericht der aktuellen Woche, ohne Zeitraumwahl, Filter oder Buttons |
| Analyse → Erholung | Heutige Einordnung, persönliche Normalbereiche, Schlafverläufe und später persönliche Einflussanalyse |
| Geplant → Übersicht → absolvierte Einheit | Detailansicht mit Zusammenfassung, Diagrammen, Trainingsqualität, Vergleich und Feedback; Rückkehr zum gleichen Kalendertag |
| Geplant → Übersicht → heutiger Tag | Kompakte Erholungseinordnung mit Link auf die vollständige Auswertung |
| Geplant → Übersicht → geplante Einheit | Trainingsziel, Zielwerte, Link zu passenden früheren Einheiten und Verpflegung |
| Geplant → Saison | Wettkämpfe, Trainingsphasen, Vorbereitungsstand und Szenarienvergleich |
| Geplant → Bibliothek | Bestehende Vorlagen |
| Ernährung → Trainingsverpflegung | Auswahl einer Einheit und zeitliche Abfolge für vorher, währenddessen und danach |
| Mehr → Athletenprofil | Ausrüstung, Verträglichkeit, Schlafziel und persönliche Vorgaben |
| Coach | Passende Schnellstarts und Verweise auf konkrete Berichte, Aktivitäten oder Wettkämpfe |

Auf kleinen Bildschirmen enthält eine Analysekarte eine Hauptaussage, wenige Kennzahlen und eine Grafik. Ausführliche Tabellen und Erklärungen werden aufgeklappt oder in einer Detailansicht geöffnet. Zeitraum und Sportfilter gelten nur für die jeweils passende Auswertung. Training und Erholung verwenden unterschiedliche Zeitfenster, wenn ihre Methoden dies benötigen.

## Gemeinsame Daten und Berechnungsregeln

Berechnungen erfolgen reproduzierbar im Backend. Der Coach bekommt begrenzte Ergebnisse mit Belegen, erklärt sie und formuliert Vorschläge. Bestehende Coach-Lesewege werden erweitert, bevor zusätzliche Tools eingeführt werden. Ein neues Tool wird nur angelegt, wenn ein bisheriger Leseweg die Verantwortung nicht sinnvoll abdecken kann.

Jede abgeleitete Kennzahl liefert Wert, Einheit, Zeitraum, Quelle, Beobachtungsdatum, Berechnungsmethode, Datenabdeckung und relevante Aktivitätsreferenzen. Unzureichende Daten liefern einen erklärten Zustand wie `insufficient_data`, statt einen geschätzten Nullwert. Abrufzeit und Messzeit bleiben getrennt. Methodische Zustände sind eine kleine gemeinsame Datenkonvention, kein allgemeines Analyse-Framework.

Metriken verwenden Zeitstempel und tatsächliche Zeitabstände. Fehlende Messungen, Pausen, Sensorausfälle und Provider-Duplikate werden explizit behandelt. Für historische Zonen und Zielbereiche gelten die Schwellen zum damaligen Zeitpunkt. Aktuelle FTP oder aktuelle Pulszonen werden nicht unbemerkt auf ältere Trainings angewendet. Fehlt die historische Grundlage, wird dies ausgewiesen.

UI-Diagramme dürfen Daten zur Darstellung verdichten. Intervallbewertung und Bestleistungen rechnen auf den geeigneten Originaldaten oder auf datierten, ausreichend genauen Provider-Ergebnissen. Die auf 2.000 Punkte begrenzte Coach-Projektion wird nicht als Grundlage für Sprintbestwerte verwendet.

Leseansichten und normale Coach-Nachrichten verwenden gespeicherte Daten. Ein fehlender Detaildatensatz wird über eine ausdrückliche Ladeaktion und einen bestehenden Sync-Job beschafft. Neue Berechnungen lösen keine dauernden Providerabrufe aus. Der Wochenrückblick lässt sich ohne AI-Aufruf anzeigen; eine Coach-Erklärung startet auf Nutzerwunsch.

Neue dauerhafte Daten werden mit dem aktuellen SQLCipher-Schema initialisiert. Schema-Erweiterungen verwenden frische, isolierte Datenverzeichnisse und Browserprofile. Es entstehen keine Migrationen oder Konvertierungen; vorhandene Installationen und Backups werden im Rahmen dieser Umsetzung nicht ersetzt. Same-build-Restart und Restore eines Backups mit dem aktuellen Schema bleiben überprüfbare Verträge.

## Reihenfolge der Arbeitspakete

| Paket | Ergebnis | Benötigt | Größe |
| --- | --- | --- | --- |
| 1 | Verlässliche Detaildaten und Aktivitätsansicht aus dem Kalender | Aktueller Stand | Groß |
| 2 | Wochenrückblick, Blockvergleich und Trainingsreiz | Paket 1; Teilbericht funktioniert auch ohne Streams | Mittel |
| 3 | Intervallqualität und strukturierter RPE je Aktivität | Paket 1 | Groß |
| 4 | Ausdauer-Effizienz, Herzfrequenzdrift und Stabilität langer Einheiten | Paket 1 | Groß |
| 5 | Erholungsbereich, Schlafdefizit und Schlafregelmäßigkeit | Vorhandene Gesundheitshistorie | Mittel |
| 6 | Leistungsprofil und Vergleich wiederkehrender Trainings | Pakete 1, 3, 4 | Groß |
| 7 | Saisonansicht und wettkampfspezifische Vorbereitung | Pakete 2, 3, 4 | Mittel |
| 8 | Plan-Simulation und Szenarienvergleich | Paket 7 und vorhandene Planvorschau | Groß |
| 9 | Trainingsverpflegung | Pakete 1, 7; bestehende Ernährung | Mittel |
| 10 | Persönliche Einflussanalyse | Paket 5 und ausreichend getaggte Tage | Mittel |
| 12 | Ausrüstung und Wartung | Paket 1 und strukturierte Zuordnung | Mittel |

Größe bezeichnet den relativen Umfang einschließlich Tests und UI. Die belastbare Zeitabschätzung folgt nach Paket 1, weil Verfügbarkeit und Qualität der Provider-Detaildaten den Aufwand der folgenden Analysen bestimmen.

## Paket 1 Detaildaten und Aktivitätsansicht

**Umsetzung:** Zuerst die öffentlich dokumentierten Intervals-Endpunkte für Detaildaten, Streams und Runden prüfen und mit synthetischen Provider-Fixtures abbilden. Danach einen gezielten, abbrechbaren Detail-Sync ergänzen. Er kennt Aktivitäts-ID, Providerrevision beziehungsweise Inhaltsfingerprint, Messkanäle, Abdeckung und Ladezustand. Bereits aktuelle Details werden wiederverwendet; geänderte Providerdaten invalidieren betroffene Ableitungen.

**Daten und Architektur:** `backend/providers/intervals.py` besitzt den Transport; `backend/sync/` besitzt Job, Wiederholung und Speicherung. `backend/activities/read_service.py` liefert lokale Details. Die Speicherform wird in diesem Paket festgelegt: vorhandene Snapshot-Speicherung verwenden, sofern Details bei inkrementellem Sync erhalten bleiben; eine fokussierte Detailtabelle ist nur nötig, wenn ihre eigene Lebensdauer oder Größe dies verlangt. Requests, Antwortgröße, Punktzahl, Laufzeit und Batchumfang erhalten harte, in Tests geprüfte Grenzen. Verfügbare Kanäle werden einzeln ausgewiesen.

**Oberfläche und Coach:** Ein Button in der absolvierten Kalenderkarte öffnet die Detailansicht. Ein authentifizierter lokaler GET liefert die bereinigte Ansicht. Fehlende Details zeigen den Button „Detaildaten laden“, dessen POST mit CSRF einen Sync-Job startet. Das Öffnen allein ruft keinen Provider auf. Die Ansicht zeigt Datum, Sport, Dauer, Belastung, verfügbare Kurven und Quellen. „Mit dem Coach besprechen“ übernimmt die genaue Aktivitätsreferenz als sichtbaren Entwurf; der Nutzer sendet ihn selbst. Browser-Zurück stellt Datum, Filter und Scrollposition wieder her.

**Abnahme:** Eine Aktivität mit vollständigen, partiellen oder fehlenden Details ist verständlich bedienbar. Zwei Aufzeichnungen desselben Trainings erzeugen eine kanonische Auswertung. Ein Timeout oder Abbruch verändert weder lokale Planung noch vorhandene gültige Details. Wiederholtes Öffnen bleibt lokal. Sensorausfälle und Datenlücken sind sichtbar. Der bestehende Soll-Ist-Vergleich im Kalender bleibt erhalten.

## Paket 2 Wochenrückblick und Trainingsreiz

**Umsetzung:** Einen deterministischen Wochenbericht aus absolvierten Aktivitäten, vorhandener Paarung zu geplanten Einheiten, Check-ins und datierten Leistungswerten bauen. Er zeigt Umfang je Sport, geplante und absolvierte Belastung, zusätzliche Einheiten, Schlüsseltrainings, verfügbare Rückmeldungen und nachvollziehbare Entwicklungen. Abgeschlossene Wochen lassen sich mit der Vorwoche oder einem gewählten Trainingsblock vergleichen; die laufende Woche wird als unvollständig gekennzeichnet.

**Metriken:** Zeit in dokumentierten Intensitätsbereichen, Verteilung harter Trainingstage und Änderungen von Umfang/Belastung. Historische Zonen und Schwellen müssen bekannt sein. Für jede Zonenverteilung die auswertbare Dauer relativ zur gesamten passenden Trainingsdauer anzeigen. Krafttraining wird nicht aus einer Herzfrequenzverteilung als Ausdauerreiz klassifiziert. Eine 80/20-Verteilung ist keine feste Bewertungsvorgabe.

**Oberfläche und Coach:** Analyse → Aktuelle Woche zeigt automatisch die aktuelle Woche von Montag bis Sonntag in der Athletenzeitzone, über alle Sportarten. Zusammenfassung und Belege sind direkt sichtbar, ohne Buttons, Filter, Zeitraumwahl oder aufzuklappende Berichtsteile. Fakten lassen sich ohne AI lesen. Der Coach kann Berichte weiterhin über seinen bestehenden Leseweg besprechen. Berechenbare Diagrammdaten werden wiederverwendet statt separat dauerhaft dupliziert.

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

## Paket 5 Persönliche Erholung und Schlaf

**Umsetzung:** Den neuen Analyse-Unterbereich Erholung einführen. HRV, Ruhepuls und Schlaf gegen persönliche datierte Verteilungen auswerten. Als vorgeschlagene Startregel ein gleitendes Fenster von 42 Tagen verwenden; unter 14 passenden Nächten keine Normalbereich-Einordnung ausgeben und bis 28 Nächten den Bereich als vorläufig kennzeichnen. Diese Zahlen sind Abdeckungsregeln für die erste Version, keine medizinischen Schwellen.

**Methodik:** Median und Quartile neben aktuellem Wert und Beobachtungsdatum zeigen. Gleichartige HRV-Messungen vergleichen; Messmethode und Providerwechsel trennen. Keine Mischung aus RMSSD, SDNN oder unterschiedlichen Messzeitpunkten. Einordnungen beschreiben Abweichungen vom eigenen Bereich. Eine Trainingsanpassung berücksichtigt zusätzlich Schmerzen, Krankheit, Motivation und bisherige Belastung.

**Schlaf:** Bestätigtes persönliches Schlafziel im Profil ergänzen. Das Defizit der letzten sieben Nächte aus bekannten Dauern und diesem Ziel ableiten, ohne einzelne lange Nächte als vollständigen Ausgleich zu behaupten. Schlafregelmäßigkeit nur mit tatsächlichen Schlafbeginn-/Endzeiten und korrekter Behandlung von Mitternacht, Zeitzone und Zeitumstellung anzeigen. Garmin-Schlafstadien bleiben Provider-Schätzungen.

**Oberfläche und Owner:** Analyse → Erholung enthält Tageskarte und Verläufe; im Kalender erscheint nur die kurze Einordnung mit Verknüpfung. Die vorhandenen Besitzer `backend/performance/recovery*.py`, `history.py`, `garmin_projection.py` und `backend/athlete/` erweitern. Gesundheitshistorie im bestehenden datierten Garmin-/Wellness-Pfad verfügbar halten.

**Abnahme:** Bei wenigen, veralteten oder inkompatiblen Messungen bleibt die Bewertung offen. Baselines enthalten keine zukünftigen Tage. Wechsel des Providers verschiebt den Normalbereich nicht unbemerkt. Fehlendes Schlafziel erzeugt kein erfundenes Defizit. Krankheit/Schmerz wird nicht durch eine günstige HRV relativiert.

## Paket 6 Leistungsprofil und wiederkehrende Trainings

**Umsetzung:** Für Radfahren zunächst beste beobachtete mittlere Leistung über 5 Sekunden, 1, 5 und 20 Minuten sowie eine Leistungs-Dauer-Kurve erstellen. Für Laufen passende Geschwindigkeits-/Distanzbestwerte anbieten. 28- und 90-Tage-Vergleiche genügen für die erste Version. Absolute Werte und W/kg werden nur mit passendem datiertem Gewicht angeboten.

**Vergleich:** Zuerst wiederkehrende Bibliotheksvorlagen und Indoor-Protokolle über stabile Referenzen vergleichen. Streckenvergleich folgt innerhalb dieses Pakets nur, wenn geeignete GPS-/Streckenreferenzen verfügbar sind. Strecke und Ergebnis werden innerhalb der privaten Anwendung verarbeitet. Eine manuelle Vergleichsgruppe ist möglich; die dauerhafte Zuordnung wird bestätigt gespeichert.

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

**Oberfläche:** Kurzer Hinweis in der geplanten Einheit, vollständige zeitliche Abfolge unter Ernährung → Trainingsverpflegung. Dort „Mit dem Coach anpassen“ und „Verzehr erfassen“ als unterschiedliche Aktionen.

**Abnahme:** Änderung von Dauer oder Intensität kennzeichnet einen älteren Vorschlag als überholt. Unvollständiges Ernährungstagebuch ergibt keinen sicheren Energiemangel. Portionen und Nährwerte stimmen mit gespeicherten Vorlagen überein. Hypothetischer oder verneinter Verzehr wird nicht gespeichert.

## Paket 10 Persönliche Einflussanalyse

**Umsetzung:** Tages-Check-ins um ausdrücklich gesetzte Tags ergänzen, etwa Reise, spätes Essen oder hoher Stress. Freitext nicht automatisch in vermeintliche Fakten umwandeln. Tags und Erholungsdaten über die Athletenzeitzone sowie die nachfolgende Nacht korrekt verbinden.

**Auswertung:** Für einen gewählten Zeitraum Anzahl, Median und Streuung von Erholung/Schlaf mit und ohne Tag vergleichen. Als vorgeschlagene Startregel mindestens zehn bekannte Tage je Gruppe verlangen; fehlendes Tag bedeutet nur dann „ohne“, wenn der Check-in diese Einordnung tatsächlich erlaubt. Unterschiede der Belastung und Datenabdeckung daneben zeigen. Mehrere gleichzeitig gesetzte Tags bleiben erkennbar.

**Oberfläche und Owner:** Unter Analyse → Erholung „Was beeinflusst deine Erholung?“. Tags unter `backend/athlete/`, Auswertung unter `backend/performance/`. Der Coach erklärt beobachtete Zusammenhänge ohne Kausalitäts- oder Diagnosebehauptung.

**Abnahme:** Wenig Daten, selektive Erfassung, fehlende Gruppenzuordnung oder Providerwechsel führen zu einer eingeschränkten Aussage. Korrigierte Tags aktualisieren das Ergebnis. Ungetaggte Tage werden nicht als bestätigter Verzicht auf Alkohol, spätes Essen oder andere Einflüsse interpretiert.

## Paket 12 Ausrüstung

**Umsetzung:** Unter Mehr → Athletenprofil Ausrüstung verwalten: Schuhe, Fahrrad und Komponenten, Sportart, Status, Anfangsstand und persönliche Wartungsintervalle. Einheiten über eine stabile Referenz zuordnen; Erfassung und Änderungen werden ausdrücklich bestätigt.

**Zähler:** Kilometer, Nutzungszeit und Wartungsstand aus kanonischen Aktivitäten und bestätigtem Anfangsstand ableiten. Wechsel einer Komponente bekommt einen eigenen Start-/Wartungszeitpunkt. Fehlende Zuordnung zählt nicht automatisch zum bevorzugten Fahrrad oder Schuh. Provider-Duplikate, korrigierte Distanz und Archivierung werden bei der Ableitung berücksichtigt.

**Oberfläche:** Ausrüstung beim Aktivitätsfeedback zuordnen; persönliche Wartungshinweise in Aktivitätsdetails und beim betroffenen Gegenstand anzeigen. Hinweise beschreiben erreichte Nutzerintervalle und behaupten keine Material- oder Verletzungsdiagnose.

**Owner:** Athletenbezogene Ausrüstungsdaten unter `backend/athlete/`, Aktivitätszuordnung unter `backend/activities/`, vorhandene Coach-Schreibwege entsprechend erweitern. Keine eigenständige neue Navigationsrubrik nötig.

**Abnahme:** Eine doppelt aufgezeichnete Fahrt zählt einmal. Umbuchung auf einen anderen Schuh korrigiert beide Zähler. Wartung setzt nur den betreffenden Wartungszähler zurück und löscht keine Historie. Archivierte Gegenstände bleiben in älteren Einheiten referenzierbar.

## Prüfung und Abschluss jedes Pakets

Für jedes Paket zuerst fokussierte Unit-Tests mit synthetischen Zeitreihen, temporärer Datenbank und gemockten Providern. Relevante Fälle sind Datenlücken, Zeitumstellung, ungleichmäßige Messabstände, Duplikate, geänderte Schwellen, Wiederholungen, Abbruch und veraltete Referenzen. Analysen benötigen bekannte Eingänge mit fachlich nachvollziehbaren erwarteten Ergebnissen; reine Spiegeltests des Implementierungscodes genügen nicht.

Bei Backend-Änderungen Ruff, Formatprüfung, mypy und `python -m compileall -q server.py backend tests` ausführen. Vor Abschluss einer Feature-PR die vollständige Unit-Suite ausführen. Bei Schema-Änderungen Schema-Vertrag, frische SQLCipher-Initialisierung, Same-build-Restart, Privacy-Export und Restore eines aktuellen Backups prüfen.

Browser-Flows auf mobile-small und desktop prüfen; zusätzliche Projekte wählen, wenn Layout oder Interaktion sie betrifft. Die Integration läuft mit einem frisch gebauten Docker-Image, isoliertem Fixture-Datenverzeichnis und frischem Browserprofil. Login/CSRF, sichere Texte/Markdown, Kalender-Zurücknavigation, Enter/Shift+Enter, PWA-Assets, Offlinezustand und relevante Berechtigungsabläufe erhalten ihre bestehenden Verträge. UI-Änderungen synchronisieren Assetversionen, Service-Worker-Cache und Contract-Tests.

Coach-Prüfungen decken direkte Aufträge, Rückfragen, Korrekturen, Verneinung und hypothetische Aussagen ab. UI und Coach verwenden dieselben berechneten Fakten. Providerdaten bleiben untrusted; Belege und Metadaten werden bereinigt. Auswertung und Erklärung speichern weder Profile noch Training noch Verzehr. Durable Änderungen brauchen die passende ausdrückliche Aktion; adaptive Planung braucht Vorschau und Freigabe. Eine Live-AI-Evaluation ist ein gesonderter, ausdrücklich autorisierter Schritt.

Jede PR beschreibt auf Englisch Nutzerproblem, Ergebnis, Abhängigkeit und Prüfung, mit Conventional-Commit-Titel. Vor der PR auf den aktuellen Zielbranch rebasen, Konflikte prüfen und Mergefähigkeit bestätigen. Keine Veröffentlichung im Rahmen der Planerstellung.

## Erste Lieferung und nächster Umsetzungsschritt

Die erste vollständige Lieferung umfasst Pakete 1 bis 4: eine Aktivität aus dem Kalender öffnen, den erreichten Trainingszweck sehen, die Ausdauerentwicklung prüfen und die Woche mit dem Coach besprechen. Paket 5 ergänzt anschließend die persönliche Erholung. Die restlichen Pakete bauen in der dokumentierten Reihenfolge darauf auf; Daten aus Paket 5 können schon während der Umsetzung weiterer Features gesammelt werden.

Der konkrete nächste Schritt ist Paket 1: dokumentierte Detail-Endpunkte und passende Fixtures prüfen, die Speicherentscheidung festhalten und den lokalen Detail-Leseweg mit Ladejob umsetzen. Erst danach die Kalenderdetailansicht integrieren. Die erste PR enthält diesen vollständigen Ablauf mit Tests; bei notwendiger Teilung liefert die erste Teil-PR die getestete Datenbasis und die unmittelbar folgende Teil-PR die bedienbare Ansicht.

## Vergleichsquellen

Die Plattformen dienen als Produktinspiration. Die Berechnungen werden unabhängig dokumentiert und mit den tatsächlich verfügbaren Daten geprüft.

- [Intervals.icu Decoupling](https://www.intervals.icu/features/decoupling/) und [Power Curve](https://www.intervals.icu/features/power-curve/).
- [TrainerRoad Workout Levels](https://support.trainerroad.com/hc/trainerroad-support/articles/360061003592-workout-levels).
- [Runalyze Funktionen](https://runalyze.com/) und [Marathon Shape](https://runalyze.com/help/article/marathon-shape).
- [Athlytic persönliche Erholung und Journal](https://athlyticapp.com/getting-started/).
- [Xert Funktionen und Forecast](https://www.baronbiosys.com/features/).
- [TrainingPeaks Fueling Insights](https://www.trainingpeaks.com/coach-blog/fueling-insights-inigo-san-millan-carbohydrate-intake/).
