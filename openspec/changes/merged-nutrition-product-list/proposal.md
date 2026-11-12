## Why

The athlete decided on 2026-11-11 and 2026-11-12 (#2266, #2267) that Ernährung ›
Produkte shows one product list for own products and database entries, and
that every product offers the same four actions: Verwenden, Bearbeiten,
Aktualisieren, Löschen, plus the favourite star. Today database entries cannot
be favourites, edited, used directly or listed with own products, and own
products cannot be re-checked by their EAN. This change provides the API the
merged list (next change) builds on.

## What Changes

- **Merged list:** `GET /api/nutrition/products?scope=all` returns own products
  and stored database foods together (a food whose EAN an own product holds is
  listed as that product), sorted by name, each with origin, fetch date,
  favourite flag, missing core fields and filled-field provenance; the search
  over name, brand and EAN covers both.
- **Favourites:** a stored database food can be a favourite; the flag survives
  re-checks.
- **Editing a database entry:** the athlete can change its values (for example
  enter a value no database has). It stays a database entry; each edited field
  is marked as the athlete's own (`manual`) and a later re-check keeps it instead
  of overwriting it. The edit is in the change history and can be undone.
- **Aktualisieren for own products:** an own product with an EAN is re-checked
  through the same database lookup (Open Food Facts, Yazio when configured); only
  its empty fields are filled, as the own product wins. Without an EAN the
  action is refused with a clear message. The athlete can add an EAN by editing.
- **Using a database entry** (diary or Coach draft) works like an own product.
- **Löschen** stays: archive for own products, "Aus Datenbank entfernen" (with
  its confirmation) for database entries.
- No schema change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: one product list; favourites, editing and
  using database entries; re-check of own products by EAN.

## Impact

- Code: `backend/nutrition/catalog.py`, `backend/nutrition/food_mirror.py`,
  `backend/nutrition/food_database.py`, `backend/nutrition/meal_library.py`,
  `backend/nutrition/diary.py` (using a database entry),
  `backend/db/repositories.py`, `backend/http_api/nutrition.py`.
- Generated docs: `docs/api-routes.md` if routes change.
- The UI follows in the next change of #2266.
