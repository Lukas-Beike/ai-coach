# Design

## Context

`FoodDatabaseService` (`backend/nutrition/food_database.py`) serves BLS (`source` default) and Open Food Facts (explicit `source`), mirroring OFF hits in `food_database_entries`, whose `food_id` check allows only `off:*`. Saved products are searched first by `ProductCatalogService.lookup_product` and the Coach read tool. Provider credentials live in `backend/provider_credentials.py` (stored overrides over environment config, applied at runtime). See proposal.md for motivation.

The Yazio API is private and unofficial: `POST /v22/oauth/token` (password and refresh grants with app-shipped client id/secret), `GET /v22/products/search`, `GET /v22/products/{id}`; non-token endpoints answer `403 version_blocked` for an unrecognized User-Agent; nutrient units are undocumented.

## Goals / Non-Goals

**Goals:** a Yazio client following the Open Food Facts client's bounded-transport pattern; a lookup chain that never lets a provider failure break local or BLS search; reuse of the existing food record, mirror and meal-component flow.

**Non-Goals:** diary sync, product writes, persisting tokens, per-athlete accounts, changing explicit-source behavior for BLS or Open Food Facts.

## Decisions

1. **Own provider module** `backend/providers/yazio.py` with `YazioClient(config_provider, opener, clock)`. The credential service replaces the runtime `Config`, so the client reads the effective config per call and drops cached tokens when the credentials change. No `server.py` import.
2. **Tokens in memory only**, guarded by a lock; refresh 60 s before expiry, password grant as fallback. A rejected login pauses further logins for 15 minutes so a wrong password cannot lock the account. Alternative (persisting tokens in the encrypted `kv` table) rejected: unnecessary secret surface, and re-login is cheap.
3. **Client identifiers are credentials.** `YAZIO_EMAIL`, `YAZIO_PASSWORD`, `YAZIO_CLIENT_ID`, `YAZIO_CLIENT_SECRET` map to stored fields `yazio_email` (masked), `yazio_password`, `yazio_client_id`, `yazio_client_secret` (secret). `YAZIO_USER_AGENT` is environment-only with a documented default, since Yazio blocks unrecognized versions and the athlete may need to update it.
4. **Normalization assumes per-1-unit nutrients and scales by 100**, then rejects implausible results (kcal over 1000 or macro sum over 100 per 100 units) as unknown rather than guessing. This is unverified against a live account and recorded as a known limitation; fixtures are synthetic.
5. **Suitable match** = a result whose name or producer contains every query word (`matches_all_terms`) and whose energy is known. Applied to Yazio and, inside the chain only, to Open Food Facts so that unrelated hits fall through to BLS. Explicit-source lookups keep current behavior.
6. **Chain placement** in `FoodDatabaseService._search` with an omitted source: Yazio configured selects the chain, otherwise BLS. Failures (`AppError`) advance to the next source; the last source's error is raised only if every source failed. Barcodes: Yazio search by barcode confirmed against the detail record's `eans`, then Open Food Facts. The notice names the answering source.
7. **Mirror and ids.** Yazio foods are stored as `yazio:<uuid>` with the same 90-day freshness and stale fallback as OFF. Mirror reads take an id-prefix filter so OFF lookups do not return Yazio rows and the reverse. `resolve()` accepts `yazio:<uuid>` by mirror, then live detail (with `servings`).
8. **Schema v14.** SQLite cannot alter a CHECK, so `food_database_entries` and `nutrition_products` are rebuilt (create new, copy, drop, rename, recreate indexes) inside the migration transaction; the frozen v13 shape is kept in schema history and every earlier supported path ends through this step.
9. **Frontend.** The Anbindungen credential form gains the four Yazio fields following the Wahoo pattern; product source mapping treats "Yazio" like the other online sources. Index query versions and the service-worker cache are bumped together.

## Risks / Trade-offs

- Unofficial API changes or blocks the client → every failure is sanitized and advances the chain; documented as unsupported.
- Unverified nutrient units → plausibility guard plus a README note; verification needs a real account and is a follow-up, not part of tests.
- The suitable-match filter on Open Food Facts changes chain-only behavior → limited to Yazio-configured installs.
- Table rebuild on a populated database → covered by populated fixtures v9 to v13, injected-failure rollback and restart tests, plus an encrypted Docker run.
