# Pacecraft · AI Coach

Pace and power, planned and analysed by your AI coach. Pacecraft is a private, mobile-first PWA for a single athlete. It reads completed training and health data from Garmin and Wahoo, keeps plans, workouts and history in an encrypted local database, and coaches through a model the athlete selects: OpenAI Responses (or a compatible endpoint) or Claude through the Anthropic Messages API, with no fallback between them (OpenAI requests use `store: false`; attachments are sent as parsed measurements without metadata and without the first and last 500 m of positions, details in [docs/operations.md](docs/operations.md)). Intervals.icu is an output target only: the app writes indoor ride workouts (for Zwift), competitions, nutrition and thresholds there when the athlete asks, and never reads activities or wellness history from it; its only reads are the read-backs of what an explicit export wrote, the one-day wellness and threshold values a metric export compares, the calendar window of a competition push and the connection check ([every call](docs/provider-endpoints.md)).

It is standalone software for a trusted LAN or private VPN (WireGuard, Tailscale). Never expose it directly to the internet; use an authenticated TLS reverse proxy if it must be reachable from outside.

## Top 10 features

1. Conversational Coach with durable turns, voice, photos and files, change receipts and undo.
2. Local training calendar and workout library for running, cycling and strength; adaptive replanning only after you approve a preview.
3. Garmin (official Personal API key plus optional unofficial login) and Wahoo as data sources, bundled into one session per workout.
4. Intervals.icu as an explicit, output-only target for workouts, competitions, nutrition and thresholds.
5. Structured strength and run workouts, sent to the Garmin watch on request.
6. Local performance methods M1-M8 (session load, fitness/fatigue/form, critical power/speed, HRV, sleep) with evidence cards.
7. Analysis of load, performance, recovery and sessions with full-resolution charts.
8. Weather, air quality, pollen and external calendars shape what the Coach plans; the weather during each outdoor session adds a heat note to its analysis.
9. Nutrition diary with local food databases, saved meals and products, and Garmin energy use.
10. Private by design: SQLCipher encryption, one athlete, installable and offline-capable PWA, privacy export and restorable backups.

All features in detail: [docs/features.md](docs/features.md).

## Quick start

Requires Docker and an `APP_PASSWORD` of at least 12 characters, which is also the database key. The container runs as UID 100 / GID 101.

```sh
mkdir -p data && chown -R 100:101 data
docker run -d --name pacecraft --restart unless-stopped \
  --read-only --security-opt no-new-privileges:true --cap-drop=ALL \
  -p 8090:8090 -v "$PWD/data:/data" --env-file ./.env -e TZ=Europe/Berlin \
  ghcr.io/lukas-beike/pacecraft:latest
```

Open `http://localhost:8090`, log in with `APP_PASSWORD`, and add the OpenAI key and providers in their cards under **Mehr > Anbindungen**. Browsers need HTTPS for installation and voice input. Compose, Unraid and reverse-proxy examples: [docs/setup.md](docs/setup.md). Never run `docker rm -v`: `/data` holds the encrypted database.

## Configuration

Set variables in the container environment or a root `.env`; `DATA_DIR` and `TZ` only in the process environment. Full reference: [docs/configuration.md](docs/configuration.md).

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `APP_PASSWORD` | none, required | Login password (12+ characters) and SQLCipher key. |
| `OPENAI_API_KEY` | none | Coach access; also settable in the app. |
| `OPENAI_MODEL` | `gpt-6-luna` | Default model deployment. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Responses-compatible endpoint (HTTPS, or loopback HTTP). |
| `ANTHROPIC_API_KEY` | none | Claude API access; also settable in the app. |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Messages-compatible endpoint (HTTPS, or loopback HTTP). |
| `TRANSCRIPTION_BASE_URL`, `TRANSCRIPTION_MODEL`, `TRANSCRIPTION_API_KEY` | none | Optional OpenAI-compatible voice transcription server, e.g. local Whisper ([setup](docs/setup.md#local-voice-transcription)). |
| `INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID` | none, `0` | Intervals.icu output target. |
| `GARMIN_PERSONAL_API_KEY` | none | Official read-only Garmin Personal API key. |
| `GARMIN_PERSONAL_API_KEY_EXPIRES` | none | Key expiry date (`YYYY-MM-DD`) for the renewal warning. |
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | none | Fallback for the optional unofficial Garmin login. |
| `GARMINTOKENS` | `<DATA_DIR>/garmin_tokens` | Legacy token file, imported once. |
| `GARMIN_FIXTURE_PATH` | none | Mock Garmin data for development. |
| `WAHOO_CLIENT_ID`, `WAHOO_CLIENT_SECRET`, `WAHOO_REDIRECT_URI` | none | Wahoo Cloud API application; all three enable Wahoo. |
| `YAZIO_EMAIL`, `YAZIO_PASSWORD` | none | Optional Yazio product lookup. |
| `YAZIO_COUNTRY` | `DE` | Yazio search region. |
| `YAZIO_USER_AGENT` | built-in | Client string Yazio accepts. |
| `CALENDAR_ICAL_URL` | none | Private read-only ICS feed. |
| `COOKIE_SECURE` | `false` | `true` behind an HTTPS proxy. |
| `TRUSTED_PROXY_IPS` | none | Proxy addresses whose `X-Forwarded-For` is trusted. |
| `DATA_RETENTION_DAYS` | `-1` | `-1` keeps everything; positive values (30-3650) prune old chats, snapshots and Coach receipts. |
| `SYNC_HISTORY_EARLIEST_DATE` | `2000-01-01` | Earliest date of the historical Garmin backfill. |
| `PORT` | `8090` | Listening port. |
| `DATA_DIR` | `/data` in the image | Encrypted database and legacy token file. |
| `TZ` | `Europe/Berlin` | Default athlete time zone. |

## Providers

| Provider | Role | Setup |
| :--- | :--- | :--- |
| Garmin | Input: activities, details, sleep, HRV, daily health, thresholds. Personal API key plus optional login for the rest; planned strength and run workouts can be sent to the watch. | [Garmin](docs/setup.md#garmin-authentication--mfa-setup) |
| Wahoo | Input: activities and FIT files, cycling FTP, weight; plan export on request. | [Wahoo](docs/setup.md#wahoo-connection) |
| Intervals.icu | Output target only, on explicit synchronization. | [Credentials](docs/setup.md#provider-credentials-in-the-app) |
| OpenAI | Coach (Responses API) and voice transcription unless a local server is configured. | [Configuration](docs/configuration.md) |
| Claude (Anthropic) | Coach as the selected alternative (Messages API). | [Configuration](docs/configuration.md) |
| Open-Meteo, DWD, ICS feeds | Weather, air quality, pollen, calendar constraints. | [Synchronization](docs/synchronization.md) |

Text and records from providers are untrusted data, never instructions.

## Canonical data model

Provider payloads are stored raw and projected into provider-neutral records: activity records, observations, and detail sets. A workout recorded by several devices becomes one session whose provider copies stay stored. Each value keeps its provenance, a per-metric source rule picks the value shown (a locally confirmed value leads for thresholds), and a newer mapper version re-projects the stored raw records without a new download (activity detail is mapped from files that are not stored and is fetched again inside the sync or replay window). See [docs/canonical-model.md](docs/canonical-model.md) and the field-by-field [canonical field map](docs/canonical-field-map.md).

## Performance methods

Load, fitness/fatigue/form, critical power and speed, session efficiency, HRV and sleep are computed locally by methods M1-M8. Each has an evidence card with its limits, backed by the literature register R1-R53: [docs/performance-methods/README.md](docs/performance-methods/README.md).

## Backup, restore and upgrades

Releases keep the athlete's encrypted database. Schema v26 (release 2.0.5, the frozen baseline) is the oldest schema the code still opens; production runs v27 (releases 2.1.2 to 2.1.9), accepted by its frozen digest; the current schema is v28. Release 2.0.5 opens a v21 to v25 database or backup first. Later schemas are upgraded in place from it in one transaction; older, unknown or newer schemas are rejected unchanged. Keep the `/data` mount and `APP_PASSWORD` when recreating the container, and never reset the data directory to fix a rejected schema. Backup download, validated restore with a pre-restore copy, privacy export and local data purge are under **Mehr**. GPS tracks from Garmin and Wahoo files are stored in the encrypted database, backup and export, never shown to the Coach or in diagnostics and logs, and deleted by the local data purge; the weather during an outdoor session is fetched from Open-Meteo with the start position rounded to two decimals (or the saved weather location) and stored without any coordinate; repeated outdoor routes are recognised from the stored tracks and shown only as a label and visit count ("Hausrunde, 5. Mal") that the athlete can rename in the activity view, and are deleted with the tracks; **Mehr** → privacy section has the "GPS-Spuren speichern" switch (default on) and, once it is off, a confirmed deletion of the stored tracks; details in [docs/operations.md](docs/operations.md) and [docs/schema-history.md](docs/schema-history.md).

## Further docs

- Using it: [features](docs/features.md), [analysis and activities](docs/analysis.md), [nutrition](docs/nutrition.md), [workout export format](docs/workout-export-format.md), [API routes](docs/api-routes.md), [view catalogue](docs/view-catalogue.md), [bootstrap contract](docs/bootstrap-contract.md).
- Running it: [setup](docs/setup.md), [configuration](docs/configuration.md), [synchronization and jobs](docs/synchronization.md), [operations](docs/operations.md).
- How it works: [architecture](docs/architecture.md), [Coach context and tools](docs/coach.md), [canonical model](docs/canonical-model.md), [provider endpoints](docs/provider-endpoints.md), [performance methods](docs/performance-methods/README.md).
- Developing: [development](docs/development.md), [testing](docs/testing.md), [Windows runtime](docs/windows-runtime.md), [dependency locks](docs/dependencies.md), [CI and releases](docs/ci-and-releases.md), [OpenSpec](docs/openspec.md), [Graphify](docs/graphify.md).

## Medical disclaimer

Pacecraft is a personal planning assistant, not a medical device. Recommendations and analytics come from AI models and heuristics. Stop at sharp pain, dizziness or signs of overtraining, and consult a physician before high-intensity training or when recovering from illness or injury.

## License

GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE).
