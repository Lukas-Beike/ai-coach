## Why

The athlete decided on 2026-11-11 (#2267) that the Coach helps complete
products: it lists incomplete ones, looks up the missing values by EAN, and
writes only empty fields. Filling several products is a bulk change, so the
Coach asks first ("Soll ich sie eintragen?") and needs the athlete's yes;
afterwards each turn shows a receipt with whole-turn undo naming each product,
field, value and origin.

## What Changes

- New read tool `list_incomplete_nutrition_products`: own products and stored
  database foods with empty core fields (energy, carbohydrates, protein, fat,
  sugar, fibre, salt), with id, name, brand, EAN, basis, origin and the missing
  field names.
- New write tool `fill_nutrition_product_gaps`: for each named product, the
  values per the product's own basis, their origin (`open_food_facts`, `yazio`,
  `bls`, or `web` from the web search added by the next change) and source page.
  Only fields that are empty at write time are written; a known value is never
  replaced and the call reports it as skipped. Each written field records its
  origin, source page and time.
- A call touching **two or more** products is a bulk change in the nutrition
  domain: it needs the athlete's confirmed request, as other bulk changes do
  (fail closed without it). One product needs no extra confirmation.
- Every write is recorded in the change history: own products as
  `nutrition_product`, stored database foods as the new undoable
  `food_database_entry`, so the turn receipt lists each product, field, value
  and origin and whole-turn undo restores the empty fields.
- Coach tool tables and coverage docs are regenerated.
- Not in this change: the web search itself (next change of #2267) and the
  incomplete marker in the product list (#2266).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: Coach fills empty product fields.
- `coach-tool-authority`: a tool may count as bulk from a lower record count.

## Impact

- Code: `backend/coach/tool_specs.py`, `backend/coach/tool_schemas.py`,
  `backend/coach/write_gate.py`, `backend/coach/change_receipts.py`, the Coach
  read and nutrition record tools, `backend/nutrition/` (gap writes),
  `backend/db/repositories.py`, `backend/change_history.py`,
  `backend/history/assembly.py` (record service for the new entity type).
- Generated docs: `docs/coach-tool-coverage.md`, `openspec/COACH_TOOLS.md`.
- No schema change.
