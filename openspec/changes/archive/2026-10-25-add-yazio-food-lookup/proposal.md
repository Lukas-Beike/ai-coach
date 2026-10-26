# Proposal

## Why

Open Food Facts and the bundled BLS cover branded and generic foods unevenly. Yazio holds a large, curated German product catalog (#1449) that the athlete already trusts, so an optional Yazio lookup ahead of Open Food Facts reduces estimated or missing nutrition values.

## What Changes

- Add an optional, read-only Yazio product source. It is configured server-side from `YAZIO_*` environment values and can be overridden in the PWA provider settings, like the other providers.
- When Yazio is configured and no source is named, food lookups use saved products, then Yazio, then Open Food Facts, then BLS, advancing when a source has no suitable match or fails. Without Yazio the current saved-products-then-BLS default is unchanged.
- Allow `yazio` as an explicit Coach lookup source and as a product/mirror source, with source attribution on every result and per-100 g/ml values plus serving options where Yazio reports them.
- **Schema v14**: the food mirror accepts `yazio:*` ids and local products accept the `yazio` source. Both table constraints are rebuilt by a data-preserving migration from v9 and later schemas.
- Document setup, lookup priority and the unofficial-API limitations.
- Excluded: Yazio diary synchronization, any Yazio write, and any real-account use in tests.

## Capabilities

### New Capabilities

### Modified Capabilities
- `food-catalog-and-meal-library`: Yazio lookup chain, explicit `yazio` source, bounded privacy-conscious Yazio transport, mirror and product source.
- `provider-connections`: optional Yazio credentials with environment defaults and stored overrides, safe status.
- `encrypted-storage-and-migrations`: supported upgrades extend to schema v14.

## Impact

- `backend/providers/` (new Yazio client), `backend/nutrition/` (food database, catalog, mirror), `backend/coach/` (lookup tool and schema), `backend/config.py`, `backend/provider_credentials.py`, `backend/observability.py`, `backend/db/` (schema, migration, repositories), `public/` (credential fields, product source mapping, cache version), README, tests and frozen schema fixtures.
- External dependency: the unofficial, unversioned Yazio mobile API; no new Python package.
