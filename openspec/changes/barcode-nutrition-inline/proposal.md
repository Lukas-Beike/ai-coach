# Proposal

## Why

Barcode results are separated from their editor by product lists, making review cumbersome. Online sugar, fibre and salt values are dropped before the product editor can show them.

## What Changes

- Place the editable product form beside a barcode result while retaining explicit local saving.
- Carry supported, valid provider label values for sugar, fibre and salt through the food record to the product form, preserving unknown values and source attribution.
- Address existing mirrored records without overwriting athlete products or silently changing recorded meals.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: Barcode review and additional label nutrient propagation.

## Impact

Provider adapters, food mirror lookup, product UI, regression tests and PWA cache assets. No new provider or database migration is intended. Evidence inspected at revision c6ddecc8: `backend/providers/open_food_facts.py`, `backend/providers/yazio.py`, `backend/nutrition/food_database.py`, `public/nutrition.js`, `public/index.html`, and existing food lookup tests. Live provider availability and actual product completeness are unverified.
