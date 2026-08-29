# Intervals Coach

Intervals Coach ist eine private, mobile-first PWA für einen Athleten. Der
Python-Server synchronisiert Intervals.icu und optional Garmin, sendet einen
reduzierten Trainingskontext an die OpenAI Responses API und speichert Chat,
Profil, Snapshots und Trainingsentwürfe lokal.

## Funktionen

- Profil, Zielwettkämpfe, Leistungswerte und Trainingshistorie in SQLite.
- Startup-Sync und manuelle bzw. angeforderte Aktualisierung von Intervals.icu.
- Optionaler Garmin-Abruf mit Deduplizierung gegen Intervals.icu; Garmin-VO₂max
  und Garmin-Laufprognosen werden in der Leistungsansicht ausdrücklich als
  „Garmin Connect“ gekennzeichnet.
- Coach-Chat mit GPT-5.6-Modellauswahl, einstellbarem Thinking Level,
  Kontextvorschau und bereinigten Logs.
- KI erstellt nur lokale, datierte Trainingsentwürfe. Jede Übertragung in den
  Intervals.icu-Kalender benötigt eine ausdrückliche Freigabe und wird vorab
  auf Kalenderkonflikte geprüft.
- Mehrwöchige Entwürfe werden als Plan gruppiert und können schrittweise
  freigegeben werden.
- Konfigurierbare Intervals.icu-Synchronisierung mit sichtbarem Zeitraum,
  Datenexport, lokaler Löschung und konfigurierbarer Aufbewahrungsdauer.
- OpenAI-Verbrauchsanzeige mit den zuletzt von der API gemeldeten verbleibenden
  Request-/Token-Kontingenten. Das Dollar-Guthaben ist nur im OpenAI-Billing
  Dashboard bzw. über berechtigte Organisationszugriffe verfügbar.

## Zielwettkämpfe und Intervals.icu

Im Profil können Zielwettkämpfe lokal angelegt und mit **Mit Intervals.icu
synchronisieren** bidirektional abgeglichen werden. Lokale Änderungen werden
als `RACE_A`, `RACE_B` oder `RACE_C` mit stabiler `external_id` übertragen.
RACE-Events aus Intervals.icu werden beim Sync in die lokale Datenbank
übernommen. Entfernte, bereits verknüpfte Remote-Events werden lokal entfernt;
lokale Löschungen werden beim nächsten Sync auch in Intervals.icu gelöscht.
Der automatische Startup- und Tages-Sync führt diesen Abgleich ebenfalls aus.

## Konfiguration

Kopiere `.env.example` nach `.env` oder setze die Variablen direkt als Docker-
bzw. Unraid-Environment-Variablen. `-e`-Werte haben Vorrang vor einer
`.env`-Datei.

Erforderlich:

```text
OPENAI_API_KEY
INTERVALS_API_KEY
INTERVALS_ATHLETE_ID=0
APP_PASSWORD=ein-langes-zufälliges-passwort
```

`APP_PASSWORD` schützt die Weboberfläche und alle API-Endpunkte außer
`/api/health`, `/api/login` und `/api/auth/status`. Dasselbe Passwort ist der
Schlüssel der SQLCipher-Datenbank. Es wird nicht gespeichert und kann nicht
wiederhergestellt werden. Wird eine bestehende unverschlüsselte Datenbank zum
ersten Mal mit `APP_PASSWORD` gestartet, wird sie automatisch verschlüsselt und
eine Datei `*.plaintext-backup-*` im Datenverzeichnis zurückbehalten.

Optional für Garmin:

```text
GARMIN_EMAIL
GARMIN_PASSWORD
GARMINTOKENS=/data/garmin_tokens
GARMIN_FIXTURE_PATH=garmin-fixture.example.json
```

Weitere Betriebsvariablen sind `DATA_RETENTION_DAYS` (`-1` = keine automatische
Löschung, Standard). Die App setzt keine eigenen OpenAI-Anfrage- oder
Tokenlimits.

## Docker / Unraid

Das Image läuft als nicht-root Benutzer und erwartet den persistenten Mount
`/data`. Der Unraid-Appdata-Ordner muss diesem Container Schreibzugriff geben.

Das Unraid-Logo liegt unter [`public/logo.png`](https://raw.githubusercontent.com/Lukas-Beike/ai-coach/main/public/logo.png).

```sh
docker pull ghcr.io/lukas-beike/ai-coach:latest
docker stop ai-coach || true
docker rm ai-coach || true
docker run -d \
  --name ai-coach \
  --restart unless-stopped \
  --read-only \
  --security-opt no-new-privileges:true \
  -p 8090:8090 \
  -v /mnt/user/appdata/ai-coach/data:/data \
  --env-file /mnt/user/appdata/ai-coach/.env \
  -e TZ=Europe/Berlin \
  ghcr.io/lukas-beike/ai-coach:latest
```

Alternativ kann lokal mit `docker build -t ai-coach:local .` gebaut werden.
Verwende niemals `docker rm -v`, damit `/data` erhalten bleibt. Für Zugriff
außerhalb des Heimnetzes ausschließlich ein privates VPN verwenden. Das
Projekt liefert bewusst kein HTTPS-Proxying; HTTP darf nicht direkt ins
öffentliche Internet exponiert werden.

In der Unraid-UI die Variablen unter **Environment variables** setzen. Nach
Änderungen an Variablen den Container neu erstellen. API-Schlüssel und
Passwörter werden nicht in der UI der Anwendung eingegeben.

Für den einmaligen Garmin-Login:

```sh
docker run --rm -it --env-file /mnt/user/appdata/ai-coach/.env \
  -v /mnt/user/appdata/ai-coach/data:/data \
  ghcr.io/lukas-beike/ai-coach:latest python /app/garmin-login.py
```

## Daten, Datenschutz und Logs

Die Anwendung schreibt die verschlüsselte Datenbank und rotierende JSONL-Logs
nach `/data`. OpenAI erhält nur den strukturierten Coaching-Kontext; API-
Schlüssel werden nie an den Browser oder den Coach-Kontext gegeben. Externe
Texte werden als untrusted data behandelt. Logs enthalten Dienst, Operation,
Pfad, Dauer und Ergebnisgrößen, aber keine Request-Payloads.

Im Bereich **System** kann der Athlet seine lokalen Daten als JSON exportieren
oder Chats, Snapshots, Entwürfe, Bibliothek, Wettkämpfe und Profil lokal
löschen. Die Datenbankdatei bleibt dabei bestehen. Ein Chat-Reset und die
lokale Löschung versuchen außerdem, die gespeicherte OpenAI-Konversation zu
löschen; für externe API-Daten gelten die jeweiligen Anbieter-Richtlinien.

## Entwicklung und Tests

```powershell
python -m unittest discover -s tests -v
python -m py_compile server.py tests/test_server.py
```

Der GitHub-Workflow führt diese Tests für Pull Requests aus und veröffentlicht
erst nach einem erfolgreichen Testlauf auf `main` nach
`ghcr.io/lukas-beike/ai-coach`. `main` ist PR-geschützt; Dependabot verwaltet
Python-, Docker- und Action-Abhängigkeiten und darf erfolgreiche Updates
automatisch zusammenführen.

Alle manuellen Commits und Pull-Request-Titel folgen Conventional Commits, zum
Beispiel `fix: Garmin-Konfiguration korrigieren` oder
`feat(sync): Intervals-Zeitraum auswählbar machen`. Das wird durch einen
eigenen GitHub-Workflow automatisch geprüft.

## Sicherheit und Grenzen

Die App ist ein privater Planungsassistent und kein Medizinprodukt. Sie sollte
nur im vertrauenswürdigen LAN oder hinter einem privaten VPN betrieben werden.
Prüfe jeden Trainingsentwurf vor der Übertragung und hole bei Verletzungen,
Krankheit oder Warnsymptomen professionellen Rat ein.
