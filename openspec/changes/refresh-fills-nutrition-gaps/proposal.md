## Why

Stored database foods often lack values such as salt, fibre, sugar or
saturated fat, and today a re-check replaces the whole stored record, so a
fresh result without a value can even erase one that was known. The athlete
decided on 2026-11-11 (#2267, points 2 and 4) that a re-check fills gaps
without losing values, and that it can be started by hand.

## What Changes

- A re-check of a stored database food (automatic after 90 days, or manual)
  takes every value the fresh result has and keeps a stored value where the
  fresh result has none; it never empties a known field.
- Stored foods report which core fields are still missing (`missing_fields`:
  energy, carbohydrates, protein, fat, sugar, fibre, salt).
- A new confirmed action re-checks one stored food online now, with the same
  gap-filling rule, and returns the refreshed food; it fails visibly and
  leaves the stored food unchanged when the database cannot be reached.
- The "Datenbank" list in Ernährung › Produkte gets an "Aktualisieren" button
  per entry. The list itself is replaced by the merged list of #2266 later.
- Not in this change: the Yazio gap fill by EAN, the Coach gap-fill tool and
  the incomplete marker in the merged list (later changes of #2267/#2266). A
  button for all incomplete entries is left out: each re-check is one online
  request under the database's rate limit, so the merged list offers it per
  entry first.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: re-checks of stored foods fill gaps and
  keep known values; manual re-check of one stored food.

## Impact

- Code: `backend/db/repositories.py` (stored food upsert),
  `backend/nutrition/food_database.py`, `backend/nutrition/meal_library.py`,
  `backend/http_api/nutrition.py` (new POST route with session and CSRF),
  `public/nutrition.js`.
- No schema change; generated route docs (`docs/api-routes.md`) are
  regenerated.
- Docs: `docs/nutrition.md`.
