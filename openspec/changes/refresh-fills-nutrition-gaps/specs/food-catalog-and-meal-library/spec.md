## ADDED Requirements

### Requirement: Re-checks fill gaps of stored foods
A re-check of a stored database food, automatic or manual, SHALL take every value the fresh result has and SHALL keep a stored value where the fresh result has none. Stored foods SHALL name their missing core fields (energy, carbohydrates, protein, fat, sugar, fibre, salt).

#### Scenario: Fresh result fills a gap
- **WHEN** a stored food without salt is re-checked and the fresh result has salt
- **THEN** the stored food has the fresh salt value and salt is no longer listed as missing.

#### Scenario: Fresh result lacks a known value
- **WHEN** a stored food with fibre is re-checked and the fresh result has no fibre
- **THEN** the stored fibre value stays and only the fetch time and the other fresh values change.

### Requirement: Manual re-check of a stored food
The athlete SHALL be able to re-check one stored database food online now through a confirmed, session- and CSRF-protected action that applies the gap-filling rule and returns the refreshed food. When the database cannot be reached or does not know the food, the action SHALL fail visibly and leave the stored food unchanged.

#### Scenario: Manual re-check succeeds
- **WHEN** the athlete confirms "Aktualisieren" on a stored food
- **THEN** the food is fetched online regardless of its age, its gaps are filled, and its fetch time is now.

#### Scenario: Database unreachable
- **WHEN** the online fetch fails during a manual re-check
- **THEN** an error is returned and the stored food, its values and its fetch time are unchanged.

#### Scenario: Unknown or unconfirmed request
- **WHEN** the request is not confirmed or names no stored food
- **THEN** it is rejected without any online request.
