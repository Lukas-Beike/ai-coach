## 1. Yazio gap fill

- [x] 1.1 After a manual re-check of an Open Food Facts entry with empty core fields, ask Yazio by EAN when configured
- [x] 1.2 Fill only empty fields on the same basis, with origin and fetch time; keep known values
- [x] 1.3 Drop a field's Yazio origin when a later Open Food Facts value fills it

## 2. Evidence and docs

- [x] 2.1 Tests: gap filled, no Yazio, no match, other basis, complete entry not asked, later Open Food Facts value wins
- [x] 2.2 Update docs/nutrition.md
