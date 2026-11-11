# Setup

Installation, reverse proxy and provider setup. The [README](../README.md#quick-start) has the short version; variables are in [configuration](configuration.md).

## Docker Run

Run the published container image with a persistent data volume and read-only container root. The app runs as UID 100 / GID 101, so on a Linux host the data directory must belong to that user before the first start:

```sh
mkdir -p /mnt/user/appdata/ai-coach/data
chown -R 100:101 /mnt/user/appdata/ai-coach/data

docker pull ghcr.io/lukas-beike/pacecraft:latest

docker run -d \
  --name pacecraft \
  --restart unless-stopped \
  --read-only \
  --security-opt no-new-privileges:true \
  --cap-drop=ALL \
  -p 8090:8090 \
  -v /mnt/user/appdata/ai-coach/data:/data \
  --env-file /mnt/user/appdata/ai-coach/.env \
  -e TZ=Europe/Berlin \
  ghcr.io/lukas-beike/pacecraft:latest
```

*Note: Never run `docker rm -v`, as the `/data` volume contains your encrypted database and any legacy plaintext Garmin token file.*

The image runs as the non-root `app` user. Application code under `/app` is owned by root and is not writable by that user; only `/data` is writable.

## Docker Compose

Create a `docker-compose.yml` file:

```yaml
services:
  pacecraft:
    image: ghcr.io/lukas-beike/pacecraft:latest
    container_name: pacecraft
    restart: unless-stopped
    read_only: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    ports:
      - "8090:8090"
    volumes:
      - ./data:/data
    env_file:
      - .env
    environment:
      - TZ=Europe/Berlin
```

Start the service. The app runs as UID 100 / GID 101, so on a Linux host give it the data directory first:

```sh
mkdir -p data
chown -R 100:101 data
docker compose up -d
```

## Unraid Deployment Guide

1. **Prepare Appdata Directory**:
   Create the storage folder on your cache pool and give it to the container user, which runs as UID 100 / GID 101:
   ```sh
   mkdir -p /mnt/user/appdata/ai-coach/data
   chown -R 100:101 /mnt/user/appdata/ai-coach/data
   chmod -R 770 /mnt/user/appdata/ai-coach/data
   ```
2. **Container Template Setup**:
   - **Repository**: `ghcr.io/lukas-beike/pacecraft:latest`
   - **Network Type**: `Bridge`
   - **Container Port**: `8090` -> **Host Port**: `8090`
   - **Container Path `/data`**: `/mnt/user/appdata/ai-coach/data` (Read/Write)
   - Upgrading from the former `ai-coach` image keeps this data path unchanged; only the repository and container name change to `pacecraft`.
   - **Environment Variables**: Add `APP_PASSWORD`, `OPENAI_API_KEY`, `INTERVALS_API_KEY`, `TZ`, etc.
   - **Icon URL**: `https://raw.githubusercontent.com/Lukas-Beike/pacecraft/main/public/logo.png`
3. **Save and Start**: Start the container and check `docker logs -f pacecraft`.

## HTTPS Reverse Proxy Setup

Modern mobile browsers require a **Secure Context (HTTPS)** to register Service Workers, install Progressive Web Apps (PWAs), and enable microphone audio recording for push-to-talk voice. Always terminate TLS using a trusted reverse proxy.

### Caddy Example
```caddy
coach.internal.domain {
    reverse_proxy pacecraft:8090 {
        header_up X-Forwarded-Proto https
    }
}
```

### Nginx Example
```nginx
server {
    listen 443 ssl http2;
    server_name coach.internal.domain;

    ssl_certificate /etc/letsencrypt/live/coach.internal.domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/coach.internal.domain/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # Disable buffering for live SSE token streaming
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```
*When deploying behind HTTPS, remember to set `COOKIE_SECURE=true` in your `.env`. Set `TRUSTED_PROXY_IPS` to the address the app sees as the proxy's connection peer so rate limits apply per real client instead of to the proxy; without it, every request is attributed to the proxy. That is the proxy host's LAN address for a separate proxy (for example `TRUSTED_PROXY_IPS=192.168.1.6`), the proxy container's address for a proxy on the same Docker network, or `127.0.0.1` or the Docker bridge gateway for a same-host proxy like the nginx example above.*

## Provider credentials in the app

Intervals.icu, OpenAI, Garmin Personal API key (with its expiry date), Wahoo and Yazio credentials can be entered under **Mehr > Anbindungen > Zugangsdaten** instead of in `.env`:

- **Where values live:** a value saved in the app is stored in the encrypted database and takes precedence. The matching environment variable is a read-only fallback that applies again after the stored value is removed.
- **Badges:** each field shows "In der App gespeichert", "Aus Umgebung" or "Nicht gesetzt". "Entfernen" deletes only the value stored in the app and asks for confirmation.
- **Secrets:** API keys, client secrets and passwords are never shown again after saving, and the form is cleared on submit. Non-secret values (OpenAI base URL, Intervals.icu athlete ID, Wahoo client ID, Garmin key expiry date) are shown as the current value.
- **Timing:** changes apply without a container restart.
- **Password re-entry:** setting the OpenAI base URL or the Wahoo client ID or secret asks for the `APP_PASSWORD` again, on top of the session, because these values decide where the OpenAI key is sent and which Wahoo app is used. A wrong or missing password changes nothing. Removing a stored value needs no password.
- **Privacy delete:** the local data purge removes stored credentials and Garmin tokens. A legacy token file at `/data/garmin_tokens` stays on disk, as every token store is preserved, but it is no longer used; delete it on the host if it should go too. It does not change the external Garmin or Intervals.icu accounts or the Wahoo account itself, but it revokes this app's Wahoo grant at Wahoo first (best effort, like "Wahoo trennen"); a failed revoke is reported after the purge, which completes either way.

## Connection checks

Each provider card under **Mehr > Anbindungen** shows a text chip (Verbunden, Nicht eingerichtet, Fehler or Nicht geprüft; never colour alone) and the section header counts them (for example "5 verbunden · 1 Fehler"). The Garmin card adds one line each for the Personal API key (valid until, expiring, expired, rejected) and the SDK login (active, renew, not set up). Each card also shows its configuration or sync state, and a separate "Verbindung" line with the last explicit check. "Verbindung prüfen" performs one bounded read-only request and never writes remotely or starts a sync. The OpenAI check does not change the OpenAI status shown elsewhere in the app. The result shows the check time and one of: successful, rejected credentials, rate limited, service unreachable, check not supported, invalid configuration, missing Wahoo permission (reconnect), check still running, or local state unreadable. A check that outlives 45 seconds is shown as still running and picked up when it finishes; the card reads again when it becomes visible. A repeat check within 10 seconds returns the stored result, except after a transient failure (unreachable or local read error), which is retried. It lives in memory only: it resets on restart and when the matching credentials change, and loading or polling the screen never contacts a provider.

| Card | Check | Limit |
| --- | --- | --- |
| OpenAI | `GET {OPENAI_BASE_URL}/models` | Compatible endpoints without a model listing (404, 405, 501) report "not supported"; 401 and 403 count as rejected. |
| Intervals.icu | `GET /athlete/{id}` | Confirms key and athlete ID, not data freshness. |
| Garmin | Personal API key exchange when a key is set, then login with the stored tokens when connected | A key alone is checkable; otherwise it needs a connection made in the app, and `GARMIN_EMAIL` without tokens or a preserved token file shows "nicht konfiguriert". Never falls back to e-mail and password, and waits for no running sync (reports "busy"). The SDK does not distinguish causes, so any failure (including an outage) asks to retry or sign in again, and a success may only show that the tokens are accepted locally. A reconnect or any other change of the stored login drops the earlier result. Fixture mode (`GARMIN_FIXTURE_PATH`) reports not supported. The check is skipped while a Garmin sync runs.  |
| Wahoo | `GET /v1/user` with the stored token | Needs a completed Wahoo connection with the `user_read` scope; without it the card asks to reconnect Wahoo. Uses the same client as the sync, so it may refresh the token, and a rejected refresh disconnects Wahoo as it does for a sync. |
| Open-Meteo | Forecast for fixed public coordinates | Needs no key; never sends the profile location. |
| Yazio | Authentication only | See below. |

The shared calendar and Open Food Facts have no check: a calendar check would be the full feed fetch, which "Synchronisieren" already performs, and Open Food Facts needs no credentials.

## Garmin Authentication & MFA Setup

Garmin Connect enforces Multi-Factor Authentication (MFA). The primary way to connect is the UI:

1. Open **Mehr > Anbindungen > Zugangsdaten** and enter your Garmin E-Mail and password, then choose "Bei Garmin anmelden". The password is sent once to the server and is never stored; the form is cleared as soon as it is submitted.
2. If Garmin requests a verification code, the card switches to a code step. Enter the code sent to your email or mobile device. "Abbrechen" returns to the login form; the pending login expires on the server after 10 minutes.
3. On success the card shows "Verbunden" with the source "In der App gespeichert". The Garmin OAuth tokens are stored in the encrypted database, not in a file.
4. **Disconnect:** "Garmin trennen" (after a confirmation) deletes the stored Garmin tokens. Already loaded data stays in the local database. A preserved token file is not used again. `GARMIN_EMAIL` and `GARMIN_PASSWORD` from the environment are not used either; Garmin syncs stay off until the next login in the app.

An existing token file at `/data/garmin_tokens` is imported once when the database has no Garmin tokens yet. The file is left in place and is not deleted by the import. Because it is plaintext JSON protected only by owner-only file permissions, keep `/data` and every backup of it on encrypted host storage, and treat the file like a password.

`GARMIN_EMAIL` and `GARMIN_PASSWORD` from `.env` remain a read-only fallback for the app's own Garmin login. If you connect through the UI, you can remove `GARMIN_PASSWORD` from `.env`; the stored tokens are then used.

## Wahoo connection

The app can connect to Wahoo through OAuth and reads its workouts. Library workouts are written to Wahoo only when you explicitly start a Wahoo library sync (see step 8).

1. Register an application in the Wahoo developer portal and set its redirect URI to `https://<app-host>/api/wahoo/callback`. This must be the HTTPS URL at which you reach the app, and it must match `WAHOO_REDIRECT_URI` exactly.
2. Set the client ID and secret under **Mehr > Anbindungen > Zugangsdaten**, or as `WAHOO_CLIENT_ID` and `WAHOO_CLIENT_SECRET` in the environment, and set `WAHOO_REDIRECT_URI` in the environment and restart the container. The redirect URI is not editable in the UI. Without all three values, the Wahoo card under **Mehr > Anbindungen** shows "Nicht konfiguriert" and explains which server variables are missing; no secret is ever shown in the browser.
3. **Connect:** in **Mehr > Anbindungen**, choose "Wahoo verbinden". The app calls `POST /api/wahoo/connect` (session and CSRF protected), which returns the Wahoo authorize URL, and the browser follows it. The callback `GET /api/wahoo/callback` needs no session (session cookies are SameSite=Strict); it is accepted only with the server-stored, single-use state that expires after 10 minutes, and always redirects to `/?wahoo=connected` or `/?wahoo=error`. The PWA reads only that outcome word, shows a confirmation or error message and removes it from the address bar.
4. **Status:** the card shows "Nicht verbunden", "Verbunden" or, after Wahoo rejected the stored refresh token, "Erneute Verbindung erforderlich" with a "Wahoo erneut verbinden" action. Wahoo also appears with its registry label in the connection summary, the data-freshness list, running-sync progress and the manual-attention notice of the status strip.
5. **Disconnect:** "Wahoo trennen" (after a confirmation) calls `POST /api/wahoo/disconnect`, which revokes access at Wahoo (best effort) and deletes the local tokens, also after the server variables were removed. Workouts that were already imported stay in the local database.
6. Tokens are stored in the encrypted database, refreshed with rotation before expiry, and excluded from exports, diagnostics and coach context. The state JSON reports only `configured`, `connected`, `scope` and `connected_at`.
7. **What is synced:** Wahoo is polled only; no webhooks are used. Once connected, the startup and daily schedulers enqueue a Wahoo refresh (default window 84 days). Workouts are stored as canonical activities with the provider `wahoo` and local dates, including duration, moving time, distance, ascent, average heart rate, cadence and power, normalized power, work (kJ) and the Training Stress Score, kept only for cross-checking: the session load is always computed locally (see Local Session Load in [features](features.md)). Calories and speed stay only in the raw record, and the workout file download URL is not stored. The sync status shows them as "Wahoo". While connected, the Wahoo card offers "Jetzt synchronisieren" (`POST /api/wahoo/sync`, queues a refresh over the default window) and "Vollständig neu synchronisieren" (`POST /api/wahoo/full-resync`, re-reads the maximum window of 90 days). A workout deleted in Wahoo is marked deleted locally after the next fully read listing, except on the window's first and last day; a listing cut off at the page limit deletes nothing. The full resync deletes no other local data and never writes to Wahoo; if Wahoo holds more workouts than one run can read, the newest are stored and the resync is reported as failed instead of complete. While it runs, scheduled and manual Wahoo syncs and plan exports are rejected with a busy message. A disconnected account is skipped with the not-connected message; stored activities are kept. Two threshold reads follow the same run: `power_zones_read` supplies the newest cycling FTP and `user_read` the profile weight. They are the lowest-priority sources for current FTP and weight, after Garmin. A Wahoo FTP or weight observed more than 90 days before the athlete's local today is not used as the current value; it stays stored for history. A read whose scope was not granted is skipped, and a 403 or 404 on either read is non-fatal while the workouts are still stored; any other failure stops the run.
8. **Explicit plan export.** A library workout is uploaded to Wahoo as a plan only by the explicit library synchronization action with the target `wahoo` (`POST /api/sync/jobs` with `{"provider": "wahoo", "type": "plan_push", "payload": {"entries": [...]}}`, using the same session and CSRF protections and the same preview hash as Intervals.icu). Intervals.icu stays the default target; the Coach and adaptive replanning never export to Wahoo. The Wahoo plan id is kept in the local remote links, so a second sync updates the same plan instead of creating a duplicate, and a plan deleted at Wahoo is created again. Without a connected Wahoo account the request is rejected with a reconnect hint and nothing is written. Wahoo plans support cycling and running workouts with time-based steps and absolute targets (`W` or `BPM`, or a pace for runs) or percentage targets of FTP, threshold or maximum heart rate, or threshold pace. The plan header carries the references of the plan's sport at export time (local zones, else Garmin, else Wahoo); a percentage target without its reference is rejected with the missing value named. The library marks a workout already exported to Wahoo as "Wahoo: synchron" or "Wahoo: geändert" by comparing the plan it would send now (text and the references its percentage steps use) with the plan last sent; an edit or an FTP or threshold change behind a percentage step marks it changed, an absolute-only workout is unaffected by threshold changes, and another provider's sync never counts. A changed workout offers "Erneut senden", which starts the same explicit plan export; the state itself never writes to Wahoo. Ramps, zone targets and other sports are rejected for that workout with a clear message; the other selected workouts still sync. Format reference: <https://cloud-api.wahooligan.com/docs/plan-json-format.pdf>.
9. **Workout files.** After a sync, the FIT files of at most 10 workouts per run are downloaded read-only and kept as full-resolution streams and laps, a failed download is retried at most three times per workout version and an empty file is not retried; the signed download link is never stored or logged.
