# Spec Delta

## ADDED Requirements

### Requirement: Yazio is an optional prioritized external food source
When Yazio is configured and a text or barcode lookup names no source, the system SHALL search saved products first, then Yazio, then Open Food Facts, then BLS for text queries and Yazio then Open Food Facts for barcodes. It SHALL advance to the next source when a source has no suitable match or is unavailable. A saved-product match SHALL prevent every external request. Without Yazio configuration the previous default SHALL apply unchanged.

#### Scenario: Local match
- **WHEN** a saved product matches the lookup
- **THEN** it is returned and no Yazio, Open Food Facts or BLS lookup runs.

#### Scenario: Yazio match
- **WHEN** no saved product matches and Yazio returns a food containing every query word with a known energy value
- **THEN** the Yazio foods are returned with source attribution and Open Food Facts is not queried.

#### Scenario: Fallthrough
- **WHEN** Yazio returns nothing suitable or fails, or Open Food Facts then does the same
- **THEN** the next source in order is used, and BLS is the final fallback.

#### Scenario: Yazio not configured
- **WHEN** no Yazio credentials are configured
- **THEN** no Yazio request is made and lookup behaves as before this change.

### Requirement: Yazio foods map into the existing food contract
The system SHALL project each Yazio result to the existing food record with a stable `yazio:` id, name, producer, source attribution, a 100-unit basis in grams or millilitres, and kcal, carbohydrate, protein and fat values. Unknown, implausible or unsupported-unit values SHALL stay unknown. Reported serving options SHALL be kept in the record. Results SHALL be untrusted data and stored in the local mirror like other online foods.

#### Scenario: Normalized result
- **WHEN** Yazio reports per-unit nutrients and a gram or millilitre base unit
- **THEN** the record states per-100 values in that unit with the source "Yazio".

#### Scenario: Unusable record
- **WHEN** a result lacks a name, reports an unsupported base unit, or has non-finite or implausible nutrient values
- **THEN** the unit or value is unknown, or the record is dropped when it has no name, and it is never guessed.

#### Scenario: Use in meals
- **WHEN** a Yazio food id is used as a meal component or ingredient with an amount in its basis unit
- **THEN** nutrition is calculated and frozen in the entry with the Yazio source, and a Yazio outage does not alter existing entries.

### Requirement: Yazio transport is bounded and credential-safe
The system SHALL authenticate with the configured account, hold tokens only in memory, and refresh or renew them before searching. It SHALL send only the food search term or barcode plus account authentication, and bound timeouts, response size and request rate.

#### Scenario: Token expiry
- **WHEN** the access token has expired
- **THEN** it is refreshed, or a new login is made when refresh is rejected, before the search.

### Requirement: Yazio failures are sanitized and isolated
The system SHALL cache successful Yazio responses, back off after rate limits and rejected logins, and map every failure to a sanitized error disclosing neither credentials, tokens, queries nor response bodies. A Yazio failure SHALL NOT fail saved-product search, BLS or Open Food Facts lookup.

#### Scenario: Rejected credentials
- **WHEN** Yazio rejects the login
- **THEN** further login attempts are paused for a backoff period, the lookup continues with the next source, and no credential appears in errors or logs.

#### Scenario: Rate limit or API change
- **WHEN** Yazio returns 429, a version block, a server error, or a response of an unexpected shape
- **THEN** the request fails safely, 429 starts a local backoff, and the chain continues.

## MODIFIED Requirements

### Requirement: Coach food reads preserve explicit source and batch results
The system SHALL support explicit database source selection and bounded batched ingredient lookup through the Coach read interface. Source selection SHALL retain separately labelled matching saved products rather than hiding them or silently replacing the chosen database.

#### Scenario: Explicit database source
- **WHEN** a Coach food query names BLS, Yazio or Open Food Facts
- **THEN** only that database is queried and matching saved products are returned separately; on a database failure, saved matches can remain available with an outage notice.

#### Scenario: Batched ingredients
- **WHEN** one through twenty distinct nonblank ingredient queries are submitted
- **THEN** case-insensitive duplicates are removed in order and each result identifies its query; a failed term does not discard successful terms, while an all-failed batch raises an error.

#### Scenario: Omitted source or invalid batch
- **WHEN** no text source is named, or a batch is malformed, oversized, empty, or combined with a barcode
- **THEN** ordinary lookup retains local-first behavior, with BLS next when Yazio is not configured and the Yazio, Open Food Facts, BLS chain when it is, and invalid batches fail before unbounded lookup work.
