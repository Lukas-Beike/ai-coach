## 1. Web search

- [ ] 1.1 Nutrition web search service: one Responses request with `web_search` and JSON output, only product data in the request
- [ ] 1.2 Keep only finite, plausible values for empty fields whose source page was cited; origin `web`, source page, untrusted notice
- [ ] 1.3 Clear "not available" result when the endpoint rejects the tool or the request fails

## 2. Coach tool

- [ ] 2.1 Read tool `search_web_for_product_values` (up to five product ids), spec, schema, handler, wiring
- [ ] 2.2 Coverage case and regenerated Coach tool docs

## 3. Evidence and docs

- [ ] 3.1 Tests: request contents, cited value kept, uncited/implausible/known dropped, endpoint rejection, failure
- [ ] 3.2 Update docs/nutrition.md
