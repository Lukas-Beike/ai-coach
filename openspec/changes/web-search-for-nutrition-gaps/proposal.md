## Why

The athlete allowed free web search as an additional source for missing product
values on 2026-11-11 (#2267): values found on the web carry origin `web` plus
the source page, and web text is untrusted data, never instructions. The
previous change lets the Coach write those values; this one lets it find them.

## What Changes

- New Coach read tool `search_web_for_product_values`: for up to five named
  products (own or stored database foods) it runs one separate Responses API
  request with the built-in `web_search` tool and a JSON output, and returns,
  per product, values for its still-empty core fields per the product's own
  basis, each with the source page.
- Only the server builds the search request: product name, brand, EAN, basis
  and the names of the missing fields. No athlete record, message or other
  context leaves the app; the Coach passes product ids only.
- A value is returned only when it is a finite number in the plausible range
  and its source page is one the search actually cited (`url_citation`); other
  values are dropped. Results carry `data_origin: web`, the source page and a
  notice that web text is untrusted data, never instructions, to be shown to
  the athlete before writing.
- Writing stays with `fill_nutrition_product_gaps` (origin `web`, source page),
  with its bulk confirmation, receipt and undo.
- Responses API only, the selected model and the configured endpoint; no other
  provider or fallback. An endpoint that rejects the `web_search` tool, or any
  failure, gives a clear "Websuche nicht verfügbar" result instead of an error.
- Not in this change: the incomplete marker in the product list (#2266).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `food-catalog-and-meal-library`: Coach web search for missing product values.

## Impact

- Code: new `backend/nutrition/web_search.py` (one Responses request, like
  `photo.py`), its wiring in the nutrition assembly and `server.py` (same
  transport as the photo reading), the Coach read tool spec, schema and
  handler.
- Generated docs: `docs/coach-tool-coverage.md`, `openspec/COACH_TOOLS.md`.
- No schema change. Endpoint support cannot be checked from development: the
  local CLIProxyAPI was not reachable for a synthetic probe, so the "not
  available" path is the tested fallback.
