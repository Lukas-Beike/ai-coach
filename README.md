# Intervals Coach

A private, mobile-first coaching PWA that keeps one persistent OpenAI Conversation, reads training data from Intervals.icu on startup or on request, synchronizes the Intervals.icu workout library in both directions, and lets the athlete schedule library templates into the calendar.

## What the MVP does

- Stores a structured athlete profile and target competitions locally in SQLite.
- Syncs 42 days of activities and wellness plus 28 days of upcoming calendar events from Intervals.icu.
- Runs one initial sync at startup; later refreshes happen when you request recent data in chat or tap the refresh button.
- When you open the chat during the morning window (05:00–11:00 in the profile timezone), runs one Garmin/Intervals.icu sync and creates a daily check-in from training load, sleep, recovery, and planned sessions.
- Keeps the same OpenAI Conversation ID across every chat turn.
- Derives current thresholds, CTL/ATL/TSB, recovery, and 7/28-day load from the latest Intervals.icu snapshot.
- Injects the confirmed profile, target competitions, derived performance, source policy, and latest training snapshot into every turn.
- Renders coach replies as safe Markdown in the chat, including headings, lists, links, emphasis, and code blocks.
- Lets you choose the active coach model from Profile; the selection is stored in the server database and applies to subsequent turns.

- The model selector currently follows the GPT-5.6 family: Sol (flagship), Terra (balanced), and Luna (cost-sensitive).
- Lets the coach create structured workouts directly in the Intervals.icu workout library using native workout text.
- Requires a tap before a draft is pushed to the calendar.
- Uses a stable `external_id`, so retrying a push updates the same app-owned event instead of creating duplicates.
- Works as an installable PWA on a phone.

## Configuration

1. Copy `.env.example` to `.env`.
2. In Intervals.icu, open **Settings → Developer Settings** and create an API key. For personal API-key use, athlete ID `0` resolves to the authenticated athlete.
3. Create an OpenAI API key and set `OPENAI_API_KEY`.
4. Optional: set `GARMIN_EMAIL`, `GARMIN_PASSWORD` and `GARMINTOKENS=/data/garmin_tokens` for the direct Garmin read-only connector. The first Garmin login may require MFA; after a successful login the tokenstore is reused.
5. Fill in the durable profile and target competitions from the Profile tab after first launch.

API secrets remain on the server and are never sent to the browser. This build intentionally has no application password and must only be exposed on a trusted local network or private VPN. The SQLite database and persistent OpenAI Conversation ID live in `DATA_DIR`.

## Run locally

Python 3.11 or newer is sufficient for the base app. Garmin support is provided by the optional `garminconnect` dependency in the Docker image. For local UI/context tests, the app also supports a JSON fixture and therefore does not require a Garmin login or the optional package.

```powershell
Copy-Item .env.example .env
# Load the values from .env into your environment, then:
python server.py
```

Open `http://localhost:8090`.

### Garmin lokal testen

Setze in `.env`:

```text
GARMIN_FIXTURE_PATH=garmin-fixture.example.json
```

Die mitgelieferte Beispieldatei kann kopiert und angepasst werden. Danach den lokalen Server neu starten und im Tab **Daten** auf **Garmin synchronisieren** klicken. Die Testdaten werden wie ein normaler Garmin-Abruf gespeichert und in den Coach-Kontext übernommen. Für echte Garmin-Daten entfernst du `GARMIN_FIXTURE_PATH`, installierst `garminconnect` in deiner lokalen Python-Umgebung und verwendest anschließend den normalen Login-/Tokenstore-Weg.

## Athlete context

SQLite is the source of truth for user-confirmed athlete facts and target competitions. The latest Intervals.icu snapshot is the source of truth for changing performance and recovery data. The OpenAI Conversation provides dialogue continuity only; the app sends the current structured context again on every response request so stale chat statements do not silently replace confirmed facts.

The chat never changes durable profile or competition data automatically. Update and confirm those values in the Profile screen.

## Run with Docker / Unraid

The Unraid deployment uses Docker CLI with image and container name `ai-coach`. From `/mnt/user/appdata/ai-coach`:

```sh
docker build -t ai-coach:local .
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
  -e PORT=8090 \
  ai-coach:local
```

The `/data` bind mount stores the SQLite database and logs. Never remove it or use `docker rm -v`. For phone access outside your home network, use a private VPN such as Tailscale. Do not expose this unauthenticated HTTP server directly to the public internet.

For the one-time interactive Garmin login after building the image, run this before starting (or while the image is available):

```sh
docker run --rm -it --env-file /mnt/user/appdata/ai-coach/.env \
  -v /mnt/user/appdata/ai-coach/data:/data \
  ai-coach:local python /app/garmin-login.py
```

The command stores the Garmin refresh token in `/data/garmin_tokens`; keep that directory private.

## Diagnostics and error logs

The server writes rotating JSONL logs to `DATA_DIR/intervals-coach.log` (1 MB per file, three backups). Errors include an event name, operation, timestamp, request ID where applicable, upstream service/path, and traceback. API keys, bearer/basic credentials, and common OpenAI key formats are redacted before anything is written.

From the Profile tab, choose **Download diagnostics** to export recent logs plus configuration flags, sync status, runtime information, and record counts. The export intentionally excludes secrets and athlete payloads, so it can be attached to an AI debugging request. The console log from `run-server.ps1` is kept separately at `DATA_DIR/server.log`.

## Test

```powershell
python -m unittest discover -s tests -v
```

## Safety and scope

This app is a planning assistant, not a medical device. It sends selected profile, training, wellness, calendar, and workout-library fields to OpenAI. It deliberately does not send API keys or all unknown fields returned by Intervals.icu. Review every library workout before scheduling it on the calendar and consult a qualified professional for injury, illness, or concerning symptoms. Because the app has no login protection, keep it local or behind a private network.
