# Proposal

## Why

Only Yazio has an explicit connection check. OpenAI, Intervals.icu, Garmin, Wahoo and Open-Meteo show configuration or sync-derived labels such as "Konfiguriert · noch nicht getestet" or "Verbunden", which can be read as a verified live connection although no request tested the credentials.

## What Changes

- Add an explicit, read-only "Verbindung prüfen" action and a separate last-check line to the OpenAI, Intervals.icu, Garmin, Wahoo and Open-Meteo cards, with the same states as Yazio: not configured, not checked, successful, rejected credentials, rate limited, unreachable and, where an endpoint lacks the probe, not supported.
- Add one authenticated local status read and one CSRF-protected check route; status never contacts a provider, results stay in memory, are tied to the effective credentials, and reset on restart or credential change.
- Keep the shared calendar and Open Food Facts without a check and document why.
- Garmin checks authenticate with stored tokens only and never fall back to e-mail and password.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `provider-connections`: uniform explicit connection checks and truthful, separated status across provider cards.

## Impact

Affects `backend/providers/connection_checks.py`, `backend/providers/connection_check_probes.py`, `backend/http_api/provider_connections.py`, HTTP assembly and dispatch, `GarminRemoteReader`, `server.py` wiring, `public/provider-checks.js`, the connections cards, service worker and README. No schema change, persistent state or remote write. Baseline: `695870a4`. Live behavior of the Garmin SDK token login and compatible OpenAI endpoints is verified only with mocks.
