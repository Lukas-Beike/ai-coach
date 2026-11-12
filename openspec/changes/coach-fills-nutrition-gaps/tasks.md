## 1. Tools

- [x] 1.1 Read tool `list_incomplete_nutrition_products` (own products and stored database foods with missing core fields)
- [x] 1.2 Write tool `fill_nutrition_product_gaps`: only empty fields, per the product's basis, with origin, source page and time; skipped and rejected items reported
- [x] 1.3 Tool spec bulk threshold from two products, enforced by the write gate

## 2. Tracking

- [x] 2.1 Change history: `nutrition_product` for own products, new undoable `food_database_entry` with its record service
- [x] 2.2 Fully tracked tool: receipt lists product, field, value, origin; whole-turn undo restores the empty fields

## 3. Evidence and docs

- [x] 3.1 Tests: listing, only-empty writes, invalid input, bulk denial and single product, receipt and undo for both kinds
- [x] 3.2 Regenerate Coach tool coverage and tool map; update docs/nutrition.md
