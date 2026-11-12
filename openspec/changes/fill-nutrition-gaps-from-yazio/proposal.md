## Why

After an Open Food Facts re-check, a stored food can still lack values such as
salt or fibre. The athlete chose Yazio on 2026-11-11 (#2267, point 3) as the
fallback database for those gaps, looked up by the product's EAN. Yazio is
already integrated (unofficial interface, the athlete's own credentials,
private use only), so no new remote target is added.

## What Changes

- When an Open Food Facts entry is re-checked (automatic after 90 days, or the
  manual "Aktualisieren") and core fields are still empty, the app asks Yazio
  for the same EAN, but only when Yazio is configured.
- Only the still-empty fields are filled, only from a Yazio product with the
  same basis unit and amount; known values are never replaced. Each filled field
  records its origin (`yazio`) and fetch time in the entry's provenance.
- The Yazio product found this way is stored as its own Yazio entry, as every
  Yazio lookup is today.
- A later Open Food Facts value for a filled field wins and drops that field's
  Yazio provenance.
- Without Yazio, after a Yazio failure or without a matching product, the entry
  stays as the re-check left it; the re-check itself still succeeds.
- No new lookup on first contact: a barcode lookup already tries Yazio first
  when it is configured.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: re-checks of Open Food Facts entries fill
  remaining gaps from Yazio by EAN.

## Impact

- Code: `backend/nutrition/food_database.py`, `backend/nutrition/food_mirror.py`.
- No schema, route or UI change.
- Docs: `docs/nutrition.md`.
