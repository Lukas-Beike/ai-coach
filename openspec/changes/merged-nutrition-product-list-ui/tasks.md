## 1. List

- [x] 1.1 Sections "Favoriten (n)" and "Alle Produkte (n)" from `GET /api/nutrition/products?scope=all`, collapsed on open, incomplete counters
- [x] 1.2 Cards: origin mark, incomplete symbol with missing field names (accessible label), favourite star for every product
- [x] 1.3 Search over all products; sections with hits open while searching
- [x] 1.4 Remove the separate "Datenbank" heading and list and the "Lokal speichern" button of stored foods

## 2. Actions

- [x] 2.1 Verwenden, Bearbeiten, Aktualisieren, Löschen on every card
- [x] 2.2 Editor: database entries edit only nutrient values; own products can take an EAN
- [x] 2.3 Aktualisieren shows the outcome, including the EAN hint; Löschen archives or removes from the database after confirmation
- [x] 2.4 Diary label for a component from a database product

## 3. Evidence and docs

- [x] 3.1 Node frontend tests and `e2e/nutrition.spec.js` (mobile, tablet-landscape, desktop), old-to-new function map in the PR
- [x] 3.2 Update docs/nutrition.md
