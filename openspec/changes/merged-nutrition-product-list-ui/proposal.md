## Why

Ernährung › Produkte shows favourites, a collapsed "Weitere Produkte" group of
own products, and a separate "Datenbank" list of stored foods with only "Lokal
speichern" and "Aus Datenbank entfernen". The athlete decided with mockups on
2026-11-11 and 2026-11-12 (#2266, #2267) on one list in which every product is
equal and incomplete products are visible. The API for it is in place.

## What Changes

- Two collapsible sections, **"Favoriten (n)"** and **"Alle Produkte (n)"**,
  both collapsed every time the page opens. "Alle Produkte" holds every product
  (own and from a database, favourites included), sorted by name.
- Next to each total, an incomplete symbol with the number of incomplete
  entries of that section (for example `37 ⚠ 5`), with an accessible label.
- Each card shows an origin mark ("eigen" or "Datenbank · Stand <date>"), and
  for an incomplete product the symbol with the names of its missing fields.
- Every product has the favourite star and four actions: **Verwenden,
  Bearbeiten, Aktualisieren, Löschen**.
  - Bearbeiten opens the product editor. For a database entry only the
    nutrient values are editable (name, brand, EAN and basis are shown read
    only); for an own product an EAN can be entered so that Aktualisieren
    works for it.
  - Aktualisieren re-checks the product online (own products need an EAN; the
    message says so) and shows the outcome.
  - Löschen archives an own product, or removes a database entry ("Aus
    Datenbank entfernen"), each after its confirmation.
- The search over name, brand and EAN covers all products; while searching,
  sections with hits open.
- The separate "Datenbank" heading and list and the "Lokal speichern" button of
  stored foods go away; nothing else is lost (barcode, label photo, manual
  entry, use, favourite, edit, delete, remove from database, search).
- In the diary, a component from a database product is labelled as a database
  product instead of a saved own product.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: the product UI becomes one list with
  sections, markers and equal actions.

## Impact

- Code: `public/index.html`, `public/nutrition.js`, `public/styles.css` (or the
  product styles file in use).
- Tests: Node frontend tests and `e2e/nutrition.spec.js` on mobile,
  tablet-landscape and desktop.
- Docs: `docs/nutrition.md`.
