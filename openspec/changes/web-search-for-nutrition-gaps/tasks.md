## 1. Web search

- [x] 1.1 Nutrition web search service: one Responses request with `web_search` and JSON output, only product data in the request
- [x] 1.2 Keep only finite, plausible values for empty fields whose source page was cited; origin `web`, source page, untrusted notice
- [x] 1.3 Clear "not available" result when the endpoint rejects the tool or the request fails

## 2. Coach tool

- [x] 2.1 Read tool `search_web_for_product_values` (up to five product ids), spec, schema, handler, wiring
- [x] 2.2 Coverage case and regenerated Coach tool docs

## 3. Evidence and docs

- [x] 3.1 Tests: request contents, cited value kept, uncited/implausible/known dropped, endpoint rejection, failure
- [x] 3.2 Update docs/nutrition.md
