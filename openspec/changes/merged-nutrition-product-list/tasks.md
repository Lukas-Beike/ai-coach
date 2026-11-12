## 1. List and favourites

- [x] 1.1 `GET /api/nutrition/products?scope=all`: own and stored database foods by name, with origin, fetch date, favourite, missing fields, filled-field provenance; search by name, brand, EAN
- [x] 1.2 Favourite flag for stored database foods, kept across re-checks

## 2. Edit, re-check, use

- [x] 2.1 Edit a stored database food: values marked `manual`, kept by later re-checks, recorded in the change history (undoable)
- [x] 2.2 Re-check an own product with an EAN: lookup, fill only empty fields; refused without an EAN
- [x] 2.3 Use a stored database food for a meal like an own product

## 3. Evidence and docs

- [x] 3.1 Tests for each scenario, HTTP contract, regenerated route docs if routes change
- [x] 3.2 Update docs/nutrition.md
