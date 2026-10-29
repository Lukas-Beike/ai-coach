# Design

## Context

Yazio (#1490) owns its check inside its client. The other providers have transports and clients but no check, and their cards derive text from configuration, sync state or usage errors.

## Goals / Non-Goals

**Goals:** One consistent check contract that separates configuration, last check and sync freshness without leaking credentials or provider text.

**Non-Goals:** Persisting results, automatic or periodic checks, remote writes, changing authentication or sync behavior, calendar and Open Food Facts checks, migrating Yazio onto the shared service.

## Decisions

- `ProviderConnectionChecks` holds injected probes. A probe is `configured`, an opaque `identity` and one read-only `check`. Results are kept in memory with a SHA-256 of the identity; a different identity reports "not checked", and a result completing after a change is discarded. Persisting would need invalidation and a migration without durable value.
- Failures map to a closed category set from `upstream_status` and reasons; error text is never stored or returned. A concurrent check for the same provider returns current status instead of a second request.
- Probes: OpenAI `GET /models` (404/405/501 become "not supported" for compatible endpoints), Intervals.icu `GET /athlete/{id}`, Wahoo `GET /user` through the refreshing client, Open-Meteo a forecast for fixed public coordinates so the profile location is not sent, Garmin a login with the stored tokens, created without e-mail or password. The Garmin SDK reports every failure as one generic error, so any failure is shown as "sign in again" rather than a specific cause. Refreshed tokens are written back by the existing compare-and-set.
- Yazio keeps its routes and card; the shared frontend module covers the other cards. Check text sits in its own line, so existing sync labels are unchanged.
- Calendar: the only read is the full feed fetch, which the existing sync owns. Open Food Facts: public, no credentials.

## Risks / Trade-offs

- [Garmin token refresh during a check could race a sync] -> the existing write-back compare-and-set decides; a failed check changes nothing.
- [Garmin reconnect keeps an older success until the next poll] -> the identity cannot include rotating tokens; documented limitation.
- [Compatible OpenAI endpoints differ] -> unsupported is reported rather than success or failure.

## Migration Plan

No schema or data change. Deploy with aligned PWA assets; rollback removes the endpoints and check lines.
