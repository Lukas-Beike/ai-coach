## Why

Own products and foods saved automatically from a database lookup live in two
tables today (`nutrition_products` and the `food_database_entries` mirror of
schema v11). The athlete decided on 2026-11-11 (#2267) that both are products
of one canonical model that differ only by origin; this replaces the
2026-10-21 decision for a separate mirror table. The later steps of #2267 and
#2266 (gap-filling refresh, Yazio fallback, Coach gap fill, one product list)
build on that model, so it comes first.

## What Changes

- Schema v27: one canonical product table. Each product carries an origin
  (`own` for the athlete's products, otherwise the food database, such as
  `open_food_facts` or `yazio`), the database's fetch time and the database's
  further fields. The mirror table is removed.
- A versioned, transactional upgrade from the production baseline v26 moves
  every mirror row into the product table without loss. A mirrored food whose
  EAN an own product holds is merged into that product: the own product wins,
  only its empty brand and same-unit nutrient fields are filled (newest food
  first), and each filled field records its origin and fetch time.
- The same rule holds at runtime: a lookup never stores a second product for
  the EAN of an own product, and saving an own product with the EAN of stored
  foods absorbs them.
- Unchanged: product list, favourites, edit, delete, "Aus Datenbank
  entfernen", the local-first read order, the 90-day re-check, Coach nutrition
  tools and the HTTP shapes of products and stored foods.
- **BREAKING** (export format only): privacy export format version 18 drops
  `food_database_entries.jsonl`; those foods are rows of
  `nutrition_products.jsonl`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: stored database foods become canonical
  products with an origin; an own product wins for its EAN.
- `encrypted-storage-and-migrations`: the baseline v26 now has a real upgrade
  step to the current schema v27.

## Impact

- Code: `backend/db/schema.py`, `backend/db/migrations.py`,
  `backend/db/schema_history.py`, `backend/db/repositories.py`,
  `backend/backup/export.py`, `backend/privacy.py`.
- Data: in-place SQLCipher upgrade v26 to v27; restore upgrades a v26 backup
  the same way. The upgrade logs how many foods were moved and how many were
  merged into own products.
- Docs: `README.md`, `docs/nutrition.md`, `docs/operations.md`,
  `docs/schema-history.md`.
- Out of scope (later changes of #2267/#2266): gap-filling refresh and manual
  refresh button, Yazio fallback by EAN, Coach gap-fill tool, merged product
  list with incomplete marker.
