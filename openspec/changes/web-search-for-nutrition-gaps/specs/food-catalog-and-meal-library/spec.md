## ADDED Requirements

### Requirement: Coach web search for missing product values
The Coach SHALL be able to search the web for the still-empty core values of up to five named products through one Responses API request with the `web_search` tool, sending only product name, brand, EAN, basis and missing field names. Only finite, plausible values whose source page the search cited SHALL be returned, with origin `web`, the source page and an untrusted-data notice.

#### Scenario: Value found and cited
- **WHEN** the search returns salt per the product's basis with a source page it cited
- **THEN** the result names the product, salt, the value, origin `web` and the source page, with the untrusted-data notice.

#### Scenario: Uncited or implausible value
- **WHEN** a returned value has no cited source page, or is not a finite number in range, or is for a field that is not empty
- **THEN** that value is dropped.

#### Scenario: Only product data leaves the app
- **WHEN** the search request is built
- **THEN** it contains only the products' name, brand, EAN, basis and missing field names, and no athlete record, message or other context.

#### Scenario: Endpoint without web search
- **WHEN** the configured endpoint rejects the `web_search` tool, or the request fails
- **THEN** the result says web search is not available, nothing is written, and the Coach turn continues.
